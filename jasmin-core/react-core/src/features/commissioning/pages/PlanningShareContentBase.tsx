import { AppstoreOutlined, UnorderedListOutlined } from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import type { FormInstance } from "antd";
import { Button, Space } from "antd";
import dayjs from "dayjs";
import type { Key } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningBulkFinalizeShareContentCreate,
  commissioningBulkUnfinalizeShareContentCreate,
  commissioningHarvestSharePlanningCreate,
  commissioningHarvestSharePlanningDestroy,
  commissioningHarvestSharePlanningUpdate,
  getCommissioningHarvestSharePlanningListQueryKey,
  useCommissioningHarvestSharePlanningList,
  useCommissioningShareVariationAmountsForPlanningRetrieve,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningGranularityRetrieveParams,
  CommissioningHarvestSharePlanningListParams,
  HarvestSharePlanningCreateRequest,
  HarvestSharePlanningRow,
  HarvestSharePlanningUpdateRequest,
} from "@shared/api/generated/models";
import { ShareTypeEnum } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { BackupModal } from "@features/commissioning/modals";
import { PlanningModeSelector, WeekSelector } from "@shared/selectors";
import { EditableTable, gatedByPermission } from "@shared/tables";
import type {
  ApiFunctions,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import {
  BulkActionButton,
  ExplainerText,
  LabeledSwitch,
  PastWarningMessage,
} from "@shared/ui";
import {
  AddShareArticleEntry,
  NoVariationColumnsBanner,
} from "@features/commissioning/components";
import {
  useCurrency,
  useNoteColumn,
  useTableRowSelection,
  useTenant,
  useUnitOptions,
} from "@hooks/index";
import {
  computePlannedAmountForDay,
  useAmountUnitSizeColumns,
  useDeliveryDayColumns,
  useFinalColumn,
  useHistoricalShareVariationAverages,
  usePlanningHarvestSharesColumns,
  usePlanningSummaryData,
  useShareArticleColumn,
  useShareArticles,
  useShareContentGranularity,
  useShareDeliveryDays,
  useShareTypeVariations,
  useWashingCleaningColumns,
} from "@features/commissioning/hooks";
import type { DeliveryDay } from "@features/commissioning/hooks/columns/useDeliveryDayColumns";
import type { ShareArticleOption } from "@features/commissioning/hooks/useShareArticles";
import type { ShareTypeVariationOption } from "@features/commissioning/hooks/useShareTypeVariations";
import { hasPurchasedSuffix, isWeekInPast } from "@shared/utils";

const currentYear = dayjs().year();
const nextWeek = dayjs().isoWeek();

interface PlanningHarvestSharesBaseProps {
  shareOption: ShareTypeEnum;
  shareArticleFilters: Record<string, boolean>;
  pageTitle: string;
  explainerKey: string;
  /** Title the article column generically ("Artikel") instead of
   *  "Gemüse / Obst" — used by the additional-share planners (honey, etc.),
   *  where the harvest framing doesn't fit. */
  genericArticleColumn?: boolean;
}

export default function PlanningHarvestSharesBase({
  shareOption,
  shareArticleFilters,
  pageTitle,
  explainerKey,
  genericArticleColumn = false,
}: PlanningHarvestSharesBaseProps) {
  const [selectedYear, setSelectedYear] = useState(currentYear);
  const [selectedWeek, setSelectedWeek] = useState<number | null>(nextWeek);
  const isPast = useMemo(
    () => isWeekInPast(selectedYear, selectedWeek),
    [selectedYear, selectedWeek],
  );
  const [columnsLoaded, setColumnsLoaded] = useState(false);

  const [showDaysTogether, setShowDaysTogether] = useState(false);
  const [showDetailedColumns, setShowDetailedColumns] = useState(true);
  const [showOnlyPlanned, setShowOnlyPlanned] = useState(false);

  const [isBackupModalOpen, setIsBackupModalOpen] = useState(false);
  const [selectedBackupData, setSelectedBackupData] =
    useState<TableRecord | null>(null);

  const { t } = useTranslation();
  const { getSetting } = useTenant();

  // Seed ``planningMode`` from ``TenantSettings.default_planning_granularity``.
  // Lazy initializer runs once on mount so subsequent tenant-settings
  // refetches don't clobber the user's manual selection via the
  // <PlanningModeSelector> dropdown (the auto-seeding ``useEffect`` below
  // also intentionally leaves the value alone in certain branches).
  const [planningMode, setPlanningMode] = useState<string>(
    () =>
      (getSetting("default_planning_granularity", "basic") as string) ||
      "basic",
  );
  const [showForecastClassification, setShowForecastClassification] =
    useState(true);
  const [showSummaryRows, setShowSummaryRows] = useState(true);
  const queryClient = useQueryClient();
  const { currencySymbol } = useCurrency();
  const { getUnitLabel } = useUnitOptions();
  const { isOffice } = useRoles();
  const permissions = useMemo(
    () => ({
      ...gatedByPermission(!isPast && isOffice),
      // Forecast-driven and stock-sourced rows are NOT planner-
      // creations — they were scaffolded by the system from
      // upstream data (a Forecast row → green + bold; leftover
      // stock from last week → green + normal weight, see
      // ``styles/planningColors.planningRowColor``). Deleting one
      // here would only nuke the planner's per-(day, variation,
      // tour, station) ShareContent line, but the underlying
      // forecast / stock would re-scaffold the row on the next
      // fetch — the planner's "delete" wouldn't stick and the
      // result would be confusing. Block delete on these so the
      // planner edits or zeros the amounts instead.
      //
      // The placeholder "Add row" entry (``key === -1``) is always
      // deletable (cancel-out of an in-flight add).
      canDeleteRecord: (record: TableRecord) => {
        if (record.key === -1) return true;
        if (record.forecast) return false;
        const stock = Number(record.current_stock_begin_of_week);
        if (Number.isFinite(stock) && stock > 0) return false;
        return true;
      },
    }),
    [isPast, isOffice],
  );

  const number_packing_stations = getSetting(
    "number_packing_stations",
    1,
  ) as number;
  const showSummaryInHarvestSharePlanningOnTop = getSetting(
    "show_summary_in_harvest_share_planning_on_top",
    true,
  ) as boolean;

  const shareTypeVariationFilters = useMemo(() => {
    return {
      physical: true,
      active_at_date: dayjs()
        .year(selectedYear)
        .isoWeek(selectedWeek ?? nextWeek)
        .isoWeekday(6)
        .format("YYYY-MM-DD"),
      share_option: shareOption,
    };
  }, [selectedYear, selectedWeek, shareOption]);

  const { shareTypeVariations, loading: shareTypeVariationsLoading } =
    useShareTypeVariations(shareTypeVariationFilters);

  // Historical-averages used to wait for `shareTypeVariations` to resolve so
  // it could pass `share_type_variation_ids`. The backend now accepts
  // `share_option` (+ `active_at_date`) and resolves IDs server-side via the
  // same filter as ShareTypeVariationViewSet — so both queries fire in
  // parallel and the planning page renders in roughly half the wall-clock
  // time it used to.
  const { data: historicalAverages } = useHistoricalShareVariationAverages({
    year: selectedYear,
    delivery_week: selectedWeek ?? nextWeek,
    share_option: shareTypeVariationFilters.share_option,
    active_at_date: shareTypeVariationFilters.active_at_date,
    years_back: 2,
    // No share-type variations → the backend resolves none and 400s; skip it.
    enabled: shareTypeVariations.length > 0,
  });

  const { refetch: refetchShareArticles } =
    useShareArticles(shareArticleFilters);

  const shareDeliveryDaysFilters = useMemo(
    () => ({
      active_at_date: dayjs()
        .year(selectedYear)
        .isoWeek(selectedWeek ?? nextWeek)
        .isoWeekday(6)
        .format("YYYY-MM-DD"),
      get_delivery_stations: true,
      need_info_on_tours: true,
    }),
    [selectedYear, selectedWeek],
  );

  const {
    shareDeliveryDays: rawShareDeliveryDays,
    toursExist,
    loading: shareDeliveryDaysLoading,
  } = useShareDeliveryDays(shareDeliveryDaysFilters);

  // Cast to extended type that correctly types delivery_stations as array
  const shareDeliveryDays = useMemo(
    () => rawShareDeliveryDays as unknown as DeliveryDay[],
    [rawShareDeliveryDays],
  );

  // When the selected week has no share-type variations or no
  // delivery-station days, the day×variation grid columns are empty — render a
  // configuration banner instead of an empty table. While either query is
  // loading, keep the grid (it shows its own spinner) so the banner doesn't
  // flash on week changes.
  const columnsLoading = shareTypeVariationsLoading || shareDeliveryDaysLoading;
  const hasVariationColumns =
    shareTypeVariations.length > 0 && shareDeliveryDays.length > 0;
  const showGrid = columnsLoading || hasVariationColumns;

  const { noteColumn } = useNoteColumn();

  const { washingCleaningColumns } = useWashingCleaningColumns();
  const { finalColumn } = useFinalColumn({
    tooltipTitle: t("tooltip.final_column_harvest_share_planning"),
  });
  const {
    shareArticleColumn,
    shareArticles: vegetables_and_fruits,
    handleUnitChange,
  } = useShareArticleColumn({
    // Restrict selectable articles to those assigned to this share option.
    filters: { ...shareArticleFilters, share_option: shareOption },
    showFruitsAndVegs: !genericArticleColumn,
    tooltip: true,
    articleDefaults: "harvest",
  });

  const { amountUnitSizeColumns } = useAmountUnitSizeColumns({
    overrides: {
      unit: {
        onFieldChange: handleUnitChange,
        disabled: (record: TableRecord) => {
          if (record.key != -1) return true;
        },
      },
      size: {
        disabled: (record: TableRecord) => {
          if (record.key != -1) return true;
        },
      },
    },
    showAmount: false,
  });

  const customEdit = useCallback(
    (record: TableRecord, form: FormInstance) => {
      if (record.key === -1) {
        const defaultValues = {
          packing_station: 1,
          size: "M",
        };

        form.setFieldsValue(defaultValues);
        return { ...record, ...defaultValues };
      }

      const processedRecord = { ...record } as Record<string, unknown>;
      const formValues: Record<string, unknown> = {};

      // First, initialize ALL possible day_ fields based on your column structure
      // this is important to ensure a correct granularity check.
      shareDeliveryDays.forEach((deliveryDay) => {
        shareTypeVariations.forEach((variation: ShareTypeVariationOption) => {
          // Basic variation field
          const basicKey = `day_${deliveryDay.id}_variation_${variation.id}`;
          processedRecord[basicKey] = processedRecord[basicKey] || 0;

          // Tour fields (if in tours mode)
          if (planningMode === "tours" && deliveryDay.used_tours) {
            deliveryDay.used_tours.forEach((tourNumber: number) => {
              const tourKey = `day_${deliveryDay.id}_variation_${variation.id}_tour_${tourNumber}`;
              processedRecord[tourKey] = processedRecord[tourKey] || 0;
            });
          }

          // Station fields (if in stations mode)
          if (planningMode === "stations" && deliveryDay.delivery_stations) {
            deliveryDay.delivery_stations.forEach((station) => {
              const stationKey = `day_${deliveryDay.id}_variation_${variation.id}_station_${station.id}`;
              processedRecord[stationKey] = processedRecord[stationKey] || 0;
            });
          }
        });

        // Planned amount and harvested fields
        const plannedKey = `day_${deliveryDay.id}_planned_amount`;
        const harvestedKey = `day_${deliveryDay.id}_harvested`;
        processedRecord[plannedKey] = processedRecord[plannedKey] || 0;
        processedRecord[harvestedKey] = processedRecord[harvestedKey] || 0;
      });

      // Now process all fields for the form
      Object.keys(processedRecord).forEach((key) => {
        if (key.startsWith("day_")) {
          if (
            processedRecord[key] === null ||
            processedRecord[key] === undefined ||
            processedRecord[key] === ""
          ) {
            processedRecord[key] = 0;
            formValues[key] = "0"; // Set as string for form input
          } else {
            formValues[key] = processedRecord[key];
          }
        } else {
          formValues[key] = processedRecord[key];
        }
      });

      // Set all values to the form - this ensures ALL fields are initialized
      form.setFieldsValue(formValues);

      return processedRecord as TableRecord;
    },
    [shareDeliveryDays, shareTypeVariations, planningMode],
  );

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => {
      // Validate seller_name for purchased items
      const shareArticle = vegetables_and_fruits?.find(
        (article: ShareArticleOption) =>
          article.id === transformedData.share_article,
      );

      if (hasPurchasedSuffix((shareArticle?.name as string) ?? "", t)) {
        if (!transformedData.seller_name && !transformedData.seller) {
          throw new Error(t("commissioning.seller_required_for_purchase"));
        }
      }

      const processedData = { ...transformedData };

      // The form's transformedData carries three parallel tiers of every
      // (day, variation) cell — bare, per-tour, per-station. Only the
      // tier matching the current planningMode is what the user actually
      // edits; the other two are derived display values that come back
      // from the list endpoint and silently ride along on every save.
      //
      // Shipping all three to the backend breaks editing:
      //   * Clearing a station cell while the bare shadow still carries
      //     the old value → the bare fans out to every station on the
      //     day and re-spawns the row the user just cleared.
      //   * Same shape in tours mode.
      //   * The "Duplicate planning entry" error we patched earlier had
      //     the same root cause — multiple tiers resolving to the same
      //     ShareContent key.
      //
      // So: drop the keys that don't belong to the active mode. Empty
      // strings on the surviving tier become 0 (the wire signal for
      // "user cleared this cell"; backend treats "all zero on the
      // surviving tier" as "no human plan").
      const STATION_RE = /_station_/;
      const TOUR_RE = /_tour_/;
      Object.keys(processedData).forEach((key) => {
        if (!key.startsWith("day_") || !key.includes("_variation_")) {
          return;
        }
        const hasStation = STATION_RE.test(key);
        const hasTour = TOUR_RE.test(key);
        const isBare = !hasStation && !hasTour;

        const matchesMode =
          (planningMode === "basic" && isBare) ||
          (planningMode === "tours" && hasTour) ||
          (planningMode === "stations" && hasStation);

        if (!matchesMode) {
          delete processedData[key];
          return;
        }
        if (processedData[key] === "") {
          processedData[key] = 0;
        }
        if (processedData[key] === "0") {
          processedData[key] = 0;
        }
      });

      return {
        ...processedData,
        year: selectedYear,
        delivery_week: selectedWeek,
      };
    },
    [planningMode, selectedYear, selectedWeek, t, vegetables_and_fruits],
  );

  const listParams = useMemo<CommissioningHarvestSharePlanningListParams>(
    () => ({
      year: selectedYear,
      delivery_week: selectedWeek ?? nextWeek,
      share_option: shareOption,
      is_past: isPast,
    }),
    [selectedYear, selectedWeek, shareOption, isPast],
  );

  // `useShareContentGranularity` accepts a partial — the hook gates the
  // actual request on `year && delivery_week`.
  const granularParams = useMemo<
    Partial<CommissioningGranularityRetrieveParams>
  >(
    () => ({
      year: selectedYear,
      delivery_week: selectedWeek ?? undefined,
      // Scope the granularity check to this page's share_option, so a simple
      // share (honey) isn't judged by a complex harvest share's per-station
      // amounts (mirrors how PackingListShell scopes by share_type).
      share_option: shareOption,
    }),
    [selectedYear, selectedWeek, shareOption],
  );
  const {
    daysOk,
    toursOk,
    refetch: refetchGranularity,
  } = useShareContentGranularity(granularParams);

  // Auto-seed planningMode when the granularity flags imply a clear best
  // mode. The "gap" branches (daysOk && !toursOk, or !daysOk && toursOk &&
  // !toursExist) are INTENTIONAL — they leave planningMode alone so the
  // user's manual selection via <PlanningModeSelector> below is preserved.
  // Don't convert to useMemo: that would force the auto-value every render
  // and override the dropdown choice.
  useEffect(() => {
    if (daysOk && toursOk) {
      setPlanningMode("basic");
    } else if (!daysOk && toursOk && toursExist) {
      setPlanningMode("tours");
    } else if (!daysOk && !toursOk) {
      setPlanningMode("stations");
    }
  }, [daysOk, toursOk, toursExist]);

  // Deliberate latch — once columns are loaded, ``columnsLoaded`` stays
  // true forever. It gates the planning-data query below
  // (``enabled: columnsLoaded``); flipping back to false during a brief
  // column refetch would cause a query-disable → re-enable → refetch storm.
  // Don't convert to a derived useMemo.
  useEffect(() => {
    if (
      shareArticleColumn &&
      amountUnitSizeColumns &&
      amountUnitSizeColumns.length > 0
    ) {
      setColumnsLoaded(true);
    }
  }, [shareArticleColumn, amountUnitSizeColumns]);

  const apiFunctions: ApiFunctions = useMemo(
    () => ({
      create: (data) =>
        commissioningHarvestSharePlanningCreate(
          data as unknown as HarvestSharePlanningCreateRequest,
        ).then((d) => ({ data: d as unknown as TableRecord })),
      update: (id, data) =>
        commissioningHarvestSharePlanningUpdate(
          id,
          data as unknown as HarvestSharePlanningUpdateRequest,
        ).then((d) => ({ data: d as unknown as TableRecord })),
      delete: (id) => commissioningHarvestSharePlanningDestroy(id),
    }),
    [],
  );

  const { data: rawData, isFetching } =
    useCommissioningHarvestSharePlanningList<
      (HarvestSharePlanningRow & Record<string, unknown>)[]
    >(listParams, {
      // Don't fetch the planning grid when there are no variation columns
      // (no share-type variations / delivery-station days) — the banner shows
      // instead, so the rows would never render.
      query: { enabled: columnsLoaded && hasVariationColumns },
    });
  const data = useMemo(
    () => (rawData ?? []) as unknown as TableRecord[],
    [rawData],
  );

  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningHarvestSharePlanningListQueryKey(listParams),
    });
  }, [queryClient, listParams]);

  // Add this useMemo to check if data contains forecast_note or stock_note
  const dataHasNotes = useMemo(() => {
    return {
      hasForecastNote: data.some(
        (record) =>
          record.forecast_note &&
          (record.forecast_note as string).trim() !== "",
      ),
      hasStockNote: data.some(
        (record) =>
          record.current_stock_note &&
          (record.current_stock_note as string).trim() !== "",
      ),
    };
  }, [data]);

  const filterDataByPlanned = useCallback(
    (dataToFilter: TableRecord[]) => {
      if (!showOnlyPlanned) {
        return dataToFilter;
      }

      return dataToFilter.filter((item) => {
        // Check if any day_ field has a value > 0
        return Object.keys(item).some((key) => {
          if (key.startsWith("day_") && key.includes("_variation_")) {
            const value = parseFloat(String(item[key])) || 0;
            return value > 0;
          }
          return false;
        });
      });
    },
    [showOnlyPlanned],
  );

  const filteredData = useMemo(() => {
    return filterDataByPlanned(data);
  }, [data, filterDataByPlanned]);

  const { data: shareVariationAmountsRaw } =
    useCommissioningShareVariationAmountsForPlanningRetrieve(listParams, {
      query: { enabled: hasVariationColumns },
    });
  const shareVariationAmounts = shareVariationAmountsRaw ?? null;

  const {
    shareVariationAmountsSummary,
    dayVariationSums,
    dayVariationCounts,
    averageWeightSubData,
    priceSumArticlesSubData,
    summaryColumns,
  } = usePlanningSummaryData({
    shareDeliveryDays,
    shareTypeVariations,
    planningMode,
    data,
    vegetables_and_fruits,
    shareVariationAmounts,
  });

  // Live still-free indicator: forecast + current stock − Σ (planned per day).
  // Per-day planned is derived from the same variation-cell values the user
  // is editing right now (see `computePlannedAmountForDay`), not from the
  // saved `day_X_planned_amount` snapshot — otherwise the indicator would
  // lag a save behind. EditableCell hands `record === liveRecord` to this
  // render while the row is in edit mode, so the result updates per keystroke.
  const calculateStillFree = useCallback(
    (record: TableRecord) => {
      const forecastAmount =
        parseFloat(String(record.forecast_available_amount)) || 0;
      const currentStock =
        parseFloat(
          String(record.available_amount_current_stock_at_time_of_planning),
        ) || 0;

      const totalPlanned = shareDeliveryDays.reduce(
        (sum, deliveryDay) =>
          sum +
          computePlannedAmountForDay(
            record as Record<string, unknown>,
            deliveryDay,
            shareTypeVariations,
            shareVariationAmountsSummary,
            planningMode,
          ),
        0,
      );

      return forecastAmount + currentStock - totalPlanned;
    },
    [
      shareDeliveryDays,
      shareTypeVariations,
      shareVariationAmountsSummary,
      planningMode,
    ],
  );

  const { deliveryDayColumns } = useDeliveryDayColumns({
    shareDeliveryDays,
    shareTypeVariations,
    showDaysTogether,
    showDetailedColumns,
    planningMode,
    showForecastClassification,
    shareVariationAmountsSummary,
  });

  const columns = usePlanningHarvestSharesColumns({
    finalColumn,
    shareArticleColumn,
    amountUnitSizeColumns,
    washingCleaningColumns,
    noteColumn,
    deliveryDayColumns,
    showDetailedColumns,
    dataHasNotes,
    calculateStillFree,
    number_packing_stations,
    currencySymbol,
    getUnitLabel,
    setIsBackupModalOpen,
    setSelectedBackupData,
  });

  const {
    selectedRowKeys,
    onSelectedRowsChange: handleRowSelectionChange,
    rowSelection: rowSelectionConfig,
  } = useTableRowSelection((record: TableRecord) => record.key === -1);

  const handleSaveSuccess = useCallback(
    (savedRecord: TableRecord, _action: "create" | "update") => {
      refetchGranularity?.();
      // Refetch policy for the planning grid: NEVER invalidate on
      // CREATE or UPDATE. ``EditableTable`` already shows the new /
      // edited row in local state where the planner put it; refetching
      // here would re-sort the list by the backend's default ordering
      // and yank the row out from under the planner mid-flow.
      //
      // The one exception is the ad-hoc clear-all case: an UPDATE
      // that wiped the slot entirely. The viewset returns a placeholder
      // with empty variation dicts and no ``share_article_name``; the
      // row's still in local state but it's effectively a ghost.
      // Detect that shape and invalidate so the refetch drops it.
      const isClearedPlaceholder =
        !savedRecord.share_article_name &&
        Object.keys((savedRecord.variations as object) ?? {}).length === 0 &&
        Object.keys((savedRecord.basic_variations as object) ?? {}).length ===
          0;
      if (isClearedPlaceholder) {
        invalidateData();
      }
    },
    [refetchGranularity, invalidateData],
  );

  const handleDeleteSuccess = useCallback(
    (_deletedKey: Key) => {
      refetchGranularity?.();
      // Deletes change the visible row count — refetch so the table
      // mirrors the server state.
      invalidateData();
    },
    [refetchGranularity, invalidateData],
  );

  return (
    <div>
      <h1>{pageTitle}</h1>

      <WeekSelector
        selectedYear={selectedYear}
        setSelectedYear={setSelectedYear}
        selectedWeek={selectedWeek}
        setSelectedWeek={setSelectedWeek}
      />
      {showGrid && (
        <div
          style={{
            marginTop: "1em",
            marginBottom: "2em",
            display: "flex",
            alignItems: "flex-start",
            gap: "2em",
          }}
        >
          <div
            className="flex-col"
            style={{
              gap: "0.5em",
              marginTop: "1em",
            }}
          >
            <LabeledSwitch
              value={showDetailedColumns}
              onChange={setShowDetailedColumns}
              label={t("commissioning.show_detailed_columns")}
              withEyeIcons
            />
            <LabeledSwitch
              value={showOnlyPlanned}
              onChange={setShowOnlyPlanned}
              label={t("commissioning.show_only_planned")}
              withEyeIcons
            />
            <LabeledSwitch
              value={showForecastClassification}
              onChange={setShowForecastClassification}
              label={t("commissioning.show_forecast_classification")}
              tooltip={t("tooltip.forecast_classification")}
              withEyeIcons
            />
            <LabeledSwitch
              value={showSummaryRows}
              onChange={setShowSummaryRows}
              label={t("commissioning.show_summary_rows")}
              withEyeIcons
            />
          </div>

          <PlanningModeSelector
            key={`${daysOk}-${toursOk}`}
            value={planningMode}
            onChange={setPlanningMode}
            disabled={isPast}
            toursExist={toursExist}
            daysOk={daysOk ?? undefined}
            toursOk={toursOk ?? undefined}
          />
        </div>
      )}
      {showGrid && (
        <div
          style={{
            marginTop: "-4em",
            marginBottom: "2em",
            display: "flex",
            alignItems: "center",
            gap: "1em",
          }}
        >
          <Space.Compact>
            <Button
              type={showDaysTogether ? "default" : "primary"}
              icon={<UnorderedListOutlined />}
              onClick={() => setShowDaysTogether(false)}
            >
              {t("commissioning.separate_days")}
            </Button>
            <Button
              type={showDaysTogether ? "primary" : "default"}
              icon={<AppstoreOutlined />}
              onClick={() => setShowDaysTogether(true)}
            >
              {t("commissioning.combined_view")}
            </Button>
          </Space.Compact>
        </div>
      )}

      {isPast && showGrid && (
        <PastWarningMessage>{t("table.past_week_readonly")}</PastWarningMessage>
      )}

      {!isPast && showGrid && (
        <div className="bulk-actions-header">
          <strong>{t("commissioning.for_selected")}</strong>
        </div>
      )}
      {!isPast && showGrid && (
        <div className="button-row-spaced">
          <BulkActionButton
            selectedIds={selectedRowKeys}
            apiFunction={(payload) =>
              commissioningBulkFinalizeShareContentCreate({
                ids: (payload.ids as string[]) ?? [],
              })
            }
            buttonText={t("commissioning.finalize")}
            buttonProps={{ type: "primary" }}
            disabled={selectedRowKeys.length === 0}
            onSuccess={invalidateData}
          />
          <BulkActionButton
            selectedIds={selectedRowKeys}
            apiFunction={(payload) =>
              commissioningBulkUnfinalizeShareContentCreate({
                ids: (payload.ids as string[]) ?? [],
              })
            }
            buttonText={t("commissioning.unfinalize")}
            disabled={selectedRowKeys.length === 0}
            onSuccess={invalidateData}
          />
        </div>
      )}

      {showGrid ? (
        <EditableTable
          key={`${selectedYear}-${selectedWeek}`}
          columns={columns}
          apiFunctions={apiFunctions}
          focusIndex="share_article_name"
          initialData={filteredData}
          loading={isFetching}
          onSaveSuccess={handleSaveSuccess}
          onDeleteSuccess={handleDeleteSuccess}
          customSave={customSave}
          customEdit={customEdit}
          permissions={permissions}
          uniqueCheck={["share_article", "unit", "size"]}
          uniqueCheckMessage={t(
            "validation.unique.share_article_unit_size_must_be_unique",
          )}
          forceInlineMode={true}
          rowSelection={!isPast ? rowSelectionConfig : undefined}
          onSelectedRowsChange={handleRowSelectionChange}
          selectedRowKeys={selectedRowKeys}
          summaryPosition={
            showSummaryInHarvestSharePlanningOnTop ? "top" : "bottom"
          }
          summaryLabelColumnIndex={1}
          summaryRows={
            showSummaryRows
              ? [
                  {
                    columns: summaryColumns,
                    label: t("commissioning.share_variation_amounts"),
                    data: shareVariationAmountsSummary,
                    style: {
                      backgroundColor: "var(--color-bg-base)",
                      fontSize: "1.1em",
                    },
                  },
                  {
                    columns: summaryColumns,
                    label: t(
                      "commissioning.summary_label_harvest_share_planning",
                    ),
                    subLabel: t("commissioning.predetermined_value"),
                    data: dayVariationSums,
                    suffix: "kg",
                    subData: averageWeightSubData,
                    subSuffix: "kg",
                    style: {
                      backgroundColor: "var(--color-bg-base)",
                      fontSize: "1.1em",
                    },
                  },
                  {
                    columns: summaryColumns,
                    label: t(
                      "commissioning.second_summary_label_harvest_share_planning",
                    ),
                    subLabel: t("commissioning.predetermined_value"),
                    data: dayVariationCounts,
                    suffix: currencySymbol,
                    subData: priceSumArticlesSubData,
                    subSuffix: currencySymbol,
                    style: {
                      backgroundColor: "var(--color-bg-base)",
                      fontSize: "1.1em",
                    },
                  },
                  {
                    columns: summaryColumns,
                    label: t("commissioning.historical_average_2y"),
                    data: (historicalAverages || {}) as Record<
                      string,
                      string | number
                    >,
                    suffix: "kg",
                    style: {
                      backgroundColor: "var(--color-info-bg)",
                      fontSize: "1.0em",
                      fontStyle: "italic",
                    },
                  },
                ]
              : []
          }
        />
      ) : (
        <NoVariationColumnsBanner />
      )}

      <BackupModal
        visible={isBackupModalOpen}
        onClose={() => {
          setIsBackupModalOpen(false);
          setSelectedBackupData(null);
        }}
        data={selectedBackupData}
        year={selectedYear}
        delivery_week={selectedWeek ?? nextWeek}
        shareOption={shareOption}
        onSave={() => {
          invalidateData(); // Refresh the main table
        }}
      />
      {showGrid && (
        <AddShareArticleEntry
          disabled={isPast}
          onSuccess={() => refetchShareArticles()}
        />
      )}
      <ExplainerText>{t(explainerKey)}</ExplainerText>
    </div>
  );
}
