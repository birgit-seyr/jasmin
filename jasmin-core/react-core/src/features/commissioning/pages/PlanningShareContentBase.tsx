import {
  AddShareArticleEntry,
  NoVariationColumnsBanner,
} from "@features/commissioning/components";
import {
  computePlannedAmountForDay,
  dayHarvestedKey,
  dayPlannedAmountKey,
  dayVariationKey,
  parseDayVariationKey,
  planningModeTier,
  useAmountUnitSizeColumns,
  useDeliveryDayColumns,
  useFinalColumn,
  useHistoricalShareTypeVariationAverages,
  usePlanningAxes,
  usePlanningHarvestSharesColumns,
  usePlanningSummaryData,
  useShareArticleColumn,
  useShareArticles,
  useShareContentGranularity,
  useWashingCleaningColumns,
} from "@features/commissioning/hooks";
import type { DeliveryDay } from "@features/commissioning/hooks/columns/useDeliveryDayColumns";
import type { ShareArticleOption } from "@features/commissioning/hooks/useShareArticles";
import type { ShareTypeVariationOption } from "@features/commissioning/hooks/useShareTypeVariations";
import { BackupModal } from "@features/commissioning/modals";
import {
  useCurrency,
  useNoteColumn,
  useTableRowSelection,
  useTenant,
  useUnitOptions,
} from "@hooks/index";
import {
  commissioningBulkFinalizeShareContentCreate,
  commissioningBulkUnfinalizeShareContentCreate,
  commissioningHarvestSharePlanningCreate,
  commissioningHarvestSharePlanningDestroy,
  commissioningHarvestSharePlanningUpdate,
  getCommissioningHarvestSharePlanningListQueryKey,
  useCommissioningHarvestSharePlanningList,
  useCommissioningShareTypeVariationAmountsForPlanningRetrieve,
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
import { hasPurchasedSuffix, isWeekInPast } from "@shared/utils";
import { useQueryClient } from "@tanstack/react-query";
import type { FormInstance } from "antd";
import { Button, Space } from "antd";
import dayjs from "dayjs";
import type { Key } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

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
  const { currencySymbol, formatCurrency } = useCurrency();
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

  // Single source of truth for the (day × variation) axes — see
  // docs/day-variation-columns-audit.md. The base grid AND the BackupModal
  // consume this same hook, so their day/variation sets can never diverge
  // (which is exactly how the modal-shows-station-less-day bug crept in).
  const {
    shareDeliveryDays: rawShareDeliveryDays,
    shareTypeVariations,
    toursExist,
    activeAtDate,
    daysLoading: shareDeliveryDaysLoading,
    variationsLoading: shareTypeVariationsLoading,
  } = usePlanningAxes({
    year: selectedYear,
    week: selectedWeek ?? nextWeek,
    shareOption,
    requireStations: true,
    needTours: true,
  });

  // Historical-averages used to wait for `shareTypeVariations` to resolve so
  // it could pass `share_type_variation_ids`. The backend now accepts
  // `share_option` (+ `active_at_date`) and resolves IDs server-side via the
  // same filter as ShareTypeVariationViewSet — so both queries fire in
  // parallel and the planning page renders in roughly half the wall-clock
  // time it used to.
  const { data: historicalAverages } = useHistoricalShareTypeVariationAverages({
    year: selectedYear,
    delivery_week: selectedWeek ?? nextWeek,
    share_option: shareOption,
    active_at_date: activeAtDate,
    years_back: 2,
    // No share-type variations → the backend resolves none and 400s; skip it.
    enabled: shareTypeVariations.length > 0,
  });

  const { refetch: refetchShareArticles } =
    useShareArticles(shareArticleFilters);

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
        const dayId = deliveryDay.id!;
        shareTypeVariations.forEach((variation: ShareTypeVariationOption) => {
          const variationId = variation.id!;
          // Basic variation field
          const basicKey = dayVariationKey({ dayId, variationId });
          processedRecord[basicKey] = processedRecord[basicKey] || 0;

          // Tour fields (if in tours mode)
          if (planningMode === "tours" && deliveryDay.used_tours) {
            deliveryDay.used_tours.forEach((tourNumber: number) => {
              const tourKey = dayVariationKey({
                dayId,
                variationId,
                tour: tourNumber,
              });
              processedRecord[tourKey] = processedRecord[tourKey] || 0;
            });
          }

          // Station fields (if in stations mode)
          if (planningMode === "stations" && deliveryDay.delivery_stations) {
            deliveryDay.delivery_stations.forEach((station) => {
              const stationKey = dayVariationKey({
                dayId,
                variationId,
                station: station.id,
              });
              processedRecord[stationKey] = processedRecord[stationKey] || 0;
            });
          }
        });

        // Planned amount and harvested fields
        const plannedKey = dayPlannedAmountKey(dayId);
        const harvestedKey = dayHarvestedKey(dayId);
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
      const activeTier = planningModeTier(planningMode);
      Object.keys(processedData).forEach((key) => {
        // Only our own (unprefixed) day×variation cells are subject to the
        // tier drop — a `backup_…` field on the record must pass through
        // untouched.
        const parsed = parseDayVariationKey(key);
        if (!parsed || parsed.prefix !== "") {
          return;
        }

        if (parsed.tier !== activeTier) {
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
      // amounts.
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

  // The purchase-cost total below tracks the grid's LIVE rows, not the list
  // query. The query is intentionally NOT invalidated on create/update (see
  // handleSaveSuccess), so the grid holds saved rows in its own state. Seed
  // from the query data — which re-syncs on week changes / delete-refetch —
  // and let the table's ``onDataChange`` keep it current through in-place
  // edits and saves, so the figure recalculates the moment a row is saved.
  const [liveData, setLiveData] = useState<TableRecord[]>([]);
  useEffect(() => {
    setLiveData(data);
  }, [data]);

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
        // Any of OUR (unprefixed) day×variation cells has a value > 0. A
        // `backup_…` field is skipped (its prefix isn't empty).
        return Object.keys(item).some((key) => {
          if (parseDayVariationKey(key)?.prefix === "") {
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

  const { data: shareTypeVariationAmountsRaw } =
    useCommissioningShareTypeVariationAmountsForPlanningRetrieve(listParams, {
      query: { enabled: hasVariationColumns },
    });
  const shareTypeVariationAmounts = shareTypeVariationAmountsRaw ?? null;

  const { shareTypeVariationAmountsSummary, summaryRows } =
    usePlanningSummaryData({
      shareDeliveryDays,
      shareTypeVariations,
      planningMode,
      data,
      vegetables_and_fruits,
      shareTypeVariationAmounts,
      t,
      currencySymbol,
      historicalAverages: historicalAverages as
        | Record<string, string | number>
        | null
        | undefined,
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
            shareTypeVariationAmountsSummary,
            planningMode,
          ),
        0,
      );

      return forecastAmount + currentStock - totalPlanned;
    },
    [
      shareDeliveryDays,
      shareTypeVariations,
      shareTypeVariationAmountsSummary,
      planningMode,
    ],
  );

  // Total money spent buying in purchased ("Zukauf") articles this week.
  // For every purchased share article, its weekly physical amount — Σ over
  // days of the per-day planned amount, which already multiplies each
  // variation's per-share cell by that variation's share count (see
  // `computePlannedAmountForDay`) — times the share content's own
  // `price_per_unit`. Non-purchased articles and rows without a price
  // contribute nothing. Computed from the already-loaded grid; no extra fetch.
  const totalPurchaseMoney = useMemo(() => {
    const articlesById = new Map(
      (vegetables_and_fruits ?? []).map((article: ShareArticleOption) => [
        article.id,
        article,
      ]),
    );

    return liveData.reduce((total, record) => {
      const article = articlesById.get(record.share_article as string);
      const isPurchased =
        Boolean(article?.is_purchased) ||
        hasPurchasedSuffix(
          (article?.name as string) ??
            (record.share_article_name as string) ??
            "",
          t,
        );
      if (!isPurchased) return total;

      const pricePerUnit = parseFloat(String(record.price_per_unit)) || 0;
      if (pricePerUnit <= 0) return total;

      const weeklyAmount = shareDeliveryDays.reduce(
        (sum, deliveryDay) =>
          sum +
          computePlannedAmountForDay(
            record as Record<string, unknown>,
            deliveryDay,
            shareTypeVariations,
            shareTypeVariationAmountsSummary,
            planningMode,
          ),
        0,
      );

      return total + pricePerUnit * weeklyAmount;
    }, 0);
  }, [
    liveData,
    vegetables_and_fruits,
    shareDeliveryDays,
    shareTypeVariations,
    shareTypeVariationAmountsSummary,
    planningMode,
    t,
  ]);

  const { deliveryDayColumns } = useDeliveryDayColumns({
    shareDeliveryDays,
    shareTypeVariations,
    showDaysTogether,
    showDetailedColumns,
    planningMode,
    showForecastClassification,
    shareTypeVariationAmountsSummary,
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
            flexWrap: "wrap",
            alignItems: "flex-start",
            gap: "1.5em 2.5em",
          }}
        >
          <div className="flex-col" style={{ gap: "0.5em" }}>
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

          {/* Planning-view controls: granularity + how days are grouped. */}
          <div className="flex-col" style={{ gap: "0.75em" }}>
            <PlanningModeSelector
              key={`${daysOk}-${toursOk}`}
              value={planningMode}
              onChange={setPlanningMode}
              disabled={isPast}
              toursExist={toursExist}
              daysOk={daysOk ?? undefined}
              toursOk={toursOk ?? undefined}
            />
            <Space.Compact>
              <Button
                type={showDaysTogether ? "default" : "primary"}
                aria-pressed={!showDaysTogether}
                onClick={() => setShowDaysTogether(false)}
              >
                {t("commissioning.separate_days")}
              </Button>
              <Button
                type={showDaysTogether ? "primary" : "default"}
                aria-pressed={showDaysTogether}
                onClick={() => setShowDaysTogether(true)}
              >
                {t("commissioning.combined_view")}
              </Button>
            </Space.Compact>
          </div>

          {/* Weekly buy-in ("Zukauf") cost, computed from the loaded grid. */}
          <div className="flex-col" style={{ gap: "0.25em" }}>
            <span className="text-secondary">
              {t("commissioning.total_purchase_cost_week")}
            </span>
            <strong>{formatCurrency(totalPurchaseMoney)}</strong>
          </div>
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
          onDataChange={setLiveData}
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
          summaryRows={showSummaryRows ? summaryRows : []}
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
        showDaysTogether={showDaysTogether}
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
