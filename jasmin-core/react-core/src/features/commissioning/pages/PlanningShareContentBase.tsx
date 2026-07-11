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
  useCommissioningDefaultShareArticlesInShareList,
  useCommissioningHarvestSharePlanningList,
  useCommissioningShareTypeVariationAmountsForPlanningRetrieve,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningGranularityRetrieveParams,
  CommissioningHarvestSharePlanningListParams,
  DefaultShareArticleInShare,
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
import { hasPurchasedSuffix, isWeekInPast, toApiDate } from "@shared/utils";
import { useQueryClient } from "@tanstack/react-query";
import type { FormInstance } from "antd";
import { Button, Space } from "antd";
import dayjs from "dayjs";
import type { Key } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

const currentYear = dayjs().year();
const nextWeek = dayjs().isoWeek();

// The article's net box price field for each unit — the source of a planning
// row's ``price_per_unit`` default (mirrors the backend's per-unit fallback in
// ShareContentService).
const PRICE_PER_UNIT_ARTICLE_FIELD: Record<string, string> = {
  KG: "net_price_for_boxes_kg",
  PCS: "net_price_for_boxes_pieces",
  PIECES: "net_price_for_boxes_pieces",
  BUNCH: "net_price_for_boxes_bunch",
};

// The article's per-item weight base for each unit — the source of a planning
// row's ``kg_per_piece``. PCS uses the per-piece weight, BUNCH the per-bunch
// weight (a distinct field); KG carries no per-item weight (the amount is
// already in kg). Combined with the row's size, e.g. ``kg_per_piece_M`` /
// ``kg_per_bunch_M``.
const KG_WEIGHT_ARTICLE_BASE: Record<string, string | null> = {
  KG: null,
  PCS: "kg_per_piece",
  PIECES: "kg_per_piece",
  BUNCH: "kg_per_bunch",
};

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

  // Article list used ONLY to source the kg/price autofill defaults. Pinned to
  // the PLANNING WEEK's price (``price_date`` = that week's Tuesday, matching
  // the backend's ``Week(...).tuesday()`` fallback) and scoped to this page's
  // share_option so the picked article is always present — otherwise the
  // net-box-price annotation defaults to TODAY's price and freezes the wrong
  // value on the row for any week at/after a scheduled price change.
  const pricingArticleFilters = useMemo(
    () => ({
      ...shareArticleFilters,
      share_option: shareOption,
      get_price_info: true,
      price_date: toApiDate(
        dayjs()
          .year(selectedYear)
          .isoWeek(selectedWeek ?? nextWeek)
          .isoWeekday(2),
      )!,
    }),
    [shareArticleFilters, shareOption, selectedYear, selectedWeek],
  );
  const { shareArticles: pricingArticles } =
    useShareArticles(pricingArticleFilters);

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

  // Per-share default amounts (``DefaultShareArticleInShare``): the configured
  // quantity of a share article inside each share-type variation. Prefetched
  // for the whole tenant and indexed by article so the (day × variation) cell
  // prefill below can run synchronously inside the in-edit field handlers.
  const { data: defaultShareArticlesRaw } =
    useCommissioningDefaultShareArticlesInShareList(
      {},
      { query: { enabled: hasVariationColumns } },
    );
  const defaultsByArticle = useMemo(() => {
    const map = new Map<string, DefaultShareArticleInShare[]>();
    (defaultShareArticlesRaw ?? []).forEach((entry) => {
      const key = String(entry.share_article);
      const list = map.get(key);
      if (list) list.push(entry);
      else map.set(key, [entry]);
    });
    return map;
  }, [defaultShareArticlesRaw]);

  // The editable day×variation cell keys for one (day, variation) in the
  // currently-active tier — mirrors ``customEdit``'s tier fan-out exactly.
  const activeTierCellKeys = useCallback(
    (deliveryDay: DeliveryDay, variationId: string): string[] => {
      const dayId = deliveryDay.id!;
      if (planningMode === "tours" && deliveryDay.used_tours) {
        return deliveryDay.used_tours.map((tour: number) =>
          dayVariationKey({ dayId, variationId, tour }),
        );
      }
      if (planningMode === "stations" && deliveryDay.delivery_stations) {
        return deliveryDay.delivery_stations.map((station) =>
          dayVariationKey({ dayId, variationId, station: station.id }),
        );
      }
      return [dayVariationKey({ dayId, variationId })];
    },
    [planningMode],
  );

  // Prefill each variation's day cells with its configured default amount for
  // the chosen article + unit.
  //   * ``replace`` (the article itself changed): the prior article's amounts
  //     are stale, so REPLACE — set each variation's cells to the new article's
  //     default and clear (0) any cell the new article has no default for.
  //   * otherwise (unit/size changed on the same article): only fill when the
  //     row carries NO amount yet, so a planner's typed values are never
  //     clobbered.
  const applyDefaultAmounts = useCallback(
    (
      articleId: string,
      unit: string,
      form: {
        getFieldValue: (field: string) => unknown;
        setFieldsValue: (values: Record<string, unknown>) => void;
      },
      replace: boolean,
    ) => {
      const rowDefaults = defaultsByArticle.get(String(articleId)) ?? [];

      if (!replace) {
        // Same article: nothing to fill if it has no defaults, and never
        // overwrite amounts already present on the row.
        if (rowDefaults.length === 0) return;
        const hasAmount = shareDeliveryDays.some((deliveryDay) =>
          shareTypeVariations.some((variation) =>
            activeTierCellKeys(deliveryDay, String(variation.id)).some(
              (key) => (parseFloat(String(form.getFieldValue(key))) || 0) > 0,
            ),
          ),
        );
        if (hasAmount) return;
      }

      const patch: Record<string, unknown> = {};
      shareTypeVariations.forEach((variation) => {
        const variationId = String(variation.id);
        const candidates = rowDefaults.filter(
          (entry) => String(entry.share_type_variation) === variationId,
        );
        // Prefer the default matching the row's unit; fall back to a
        // unit-agnostic default, then to whatever is configured.
        const match =
          candidates.find((entry) => (entry.unit ?? "") === (unit ?? "")) ??
          candidates.find((entry) => !entry.unit) ??
          candidates[0];
        const quantity = match ? parseFloat(String(match.quantity)) : NaN;
        const value =
          Number.isFinite(quantity) && quantity > 0 ? String(quantity) : null;
        shareDeliveryDays.forEach((deliveryDay) => {
          activeTierCellKeys(deliveryDay, variationId).forEach((key) => {
            if (value !== null) patch[key] = value;
            else if (replace) patch[key] = "0";
          });
        });
      });

      if (Object.keys(patch).length > 0) {
        form.setFieldsValue(patch);
      }
    },
    [defaultsByArticle, shareDeliveryDays, shareTypeVariations, activeTierCellKeys],
  );

  // Article-derived row defaults. kg/piece is SIZE-specific
  // (``kg_per_piece_<size>``); price_per_unit is UNIT-specific (the article's
  // net box price). Both are pure functions of the chosen article + unit +
  // size, so they refresh whenever any of those change.
  const pricingArticlesById = useMemo(
    () =>
      new Map(
        (pricingArticles ?? []).map((article) => [String(article.id), article]),
      ),
    [pricingArticles],
  );

  const applyArticlePricingDefaults = useCallback(
    (
      articleId: string,
      unit: string,
      form: {
        getFieldValue: (field: string) => unknown;
        setFieldsValue: (values: Record<string, unknown>) => void;
      },
      articleChanged: boolean,
    ) => {
      const article = pricingArticlesById.get(String(articleId)) as
        | Record<string, unknown>
        | undefined;
      if (!article) return;

      const patch: Record<string, unknown> = {};
      const unitKey = String(unit).toUpperCase();
      const size = String(form.getFieldValue("size") ?? "");

      // kg/item weight is fully derived from (article, unit, size), so always
      // reflect the current state: the per-PIECE weight for PCS, the per-BUNCH
      // weight for BUNCH, and none for KG. Clearing when this unit/size has no
      // source weight (KG, or a bunch article lacking a per-bunch weight) stops
      // a stale piece-weight from lingering after a unit switch.
      const weightBase = KG_WEIGHT_ARTICLE_BASE[unitKey];
      const kgWeight =
        weightBase && size ? article[`${weightBase}_${size}`] : undefined;
      patch.kg_per_piece =
        kgWeight != null && kgWeight !== "" ? kgWeight : null;

      const priceField = PRICE_PER_UNIT_ARTICLE_FIELD[unitKey];
      const price = priceField ? article[priceField] : undefined;
      if (price != null && price !== "") {
        patch.price_per_unit = price;
      } else if (articleChanged) {
        patch.price_per_unit = null;
      }

      if (Object.keys(patch).length > 0) {
        form.setFieldsValue(patch);
      }
    },
    [pricingArticlesById],
  );

  // Tracks the article the in-edit row currently carries, so applyRowDefaults
  // can tell an ARTICLE change (→ replace kg/price/amounts) from a unit/size
  // change on the same article (→ refresh kg/price, guard amounts). Seeded by
  // customEdit when a row enters edit mode.
  const previousArticleIdRef = useRef<string | null>(null);
  // A stock-only row is a computed placeholder (is_stock_only + current_stock,
  // no ShareContent). When the planner turns it into a real row by adding an
  // amount, EditableTable's in-place merge keeps the stale stock-only fields
  // the update response doesn't carry — so that slot must refetch on save.
  // Remembered on edit-entry, read in handleSaveSuccess.
  const editedStockOnlyRef = useRef(false);

  // Single entry point wired into the article / unit / size field handlers:
  // refresh the article-derived kg/price, then prefill the per-variation
  // default amounts. On an ARTICLE change both replace the prior article's
  // values; on a unit/size change kg/price refresh in place and amounts are
  // only prefilled when the row is still empty.
  const applyRowDefaults = useCallback(
    (
      articleId: string,
      unit: string,
      form: {
        getFieldValue: (field: string) => unknown;
        setFieldsValue: (values: Record<string, unknown>) => void;
      },
    ) => {
      const articleChanged =
        previousArticleIdRef.current !== String(articleId);
      previousArticleIdRef.current = String(articleId);
      applyArticlePricingDefaults(articleId, unit, form, articleChanged);
      applyDefaultAmounts(articleId, unit, form, articleChanged);
    },
    [applyArticlePricingDefaults, applyDefaultAmounts],
  );

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
    // After the built-in article/unit autofill, set the article-derived
    // kg/piece + price_per_unit and prefill the per-variation default amounts.
    onDefaultsApplied: applyRowDefaults,
  });

  // Memoized so its identity is stable across renders. An inline literal here
  // would make ``amountUnitSizeColumns`` (which memoizes on ``overrides``) — and
  // thus the whole ``columns`` config — churn every render, which re-fires
  // EditableTable's initialData-sync effect and needlessly re-seeds the grid.
  const amountUnitSizeOverrides = useMemo(
    () => ({
      unit: {
        onFieldChange: handleUnitChange,
        disabled: (record: TableRecord) => {
          if (record.key != -1) return true;
        },
      },
      size: {
        onFieldChange: (
          _size: unknown,
          _record: TableRecord,
          form: {
            getFieldValue: (field: string) => unknown;
            setFieldsValue: (values: Record<string, unknown>) => void;
          },
        ) => {
          // On an unsaved row the article id lives under ``share_article_name``
          // (the foreignKey display field) until it is persisted — mirror
          // handleUnitChange's fallback so a size change actually re-derives.
          const articleId = (form.getFieldValue("share_article") ??
            form.getFieldValue("share_article_name")) as string | undefined;
          const unit = form.getFieldValue("unit") as string | undefined;
          if (articleId) applyRowDefaults(articleId, unit ?? "", form);
        },
        disabled: (record: TableRecord) => {
          if (record.key != -1) return true;
        },
      },
    }),
    [handleUnitChange, applyRowDefaults],
  );

  const { amountUnitSizeColumns } = useAmountUnitSizeColumns({
    overrides: amountUnitSizeOverrides,
    showAmount: false,
  });

  const customEdit = useCallback(
    (record: TableRecord, form: FormInstance) => {
      // Seed the article baseline so a later unit/size change on this row is
      // NOT mistaken for an article change (which would replace amounts). A new
      // row (key === -1) carries no article yet → null.
      previousArticleIdRef.current = record.share_article
        ? String(record.share_article)
        : null;
      editedStockOnlyRef.current = record.is_stock_only === true;
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
  // handleSaveSuccess — the cache is patched in place via setQueryData
  // instead), so the grid holds saved rows in its own state. Seed from the
  // query data — which re-syncs on week changes / delete-refetch / the
  // save-time cache patch — and let the table's ``onDataChange`` keep it
  // current through in-place edits, so the figure recalculates per keystroke.
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
    formatCurrency,
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
    (savedRecord: TableRecord, action: "create" | "update") => {
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
      // A stock-only placeholder that just became a real planned row: the
      // in-place merge keeps its stale is_stock_only / current_stock fields
      // (the update response doesn't carry them), so refetch to recompute the
      // slot cleanly — same rationale as the cleared-placeholder case above.
      const wasStockOnlyUpdate = action === "update" && editedStockOnlyRef.current;
      editedStockOnlyRef.current = false;
      if (isClearedPlaceholder || wasStockOnlyUpdate) {
        invalidateData();
        return;
      }
      // Patch the list CACHE in place with the saved row (setQueryData — no
      // refetch, so no re-sort). Without this the cache keeps the PRE-save
      // row, and EditableTable's initialData-sync effect re-seeds the grid
      // from it whenever the effect re-fires — its deps include the row
      // transform, which changes identity with the columns config, a routine
      // occurrence right after a save (granularity refetch / summary-row
      // rebuild re-renders). That re-seed silently reverted just-saved
      // amounts to their stale values until the next real refetch.
      //
      // The response fully re-describes the slot's dynamic ``day_*`` cells,
      // so drop the row's old ``day_*`` keys before overlaying: a cleared
      // cell's backing ShareContent is deleted server-side and its key is
      // simply ABSENT from the response — a plain spread-merge would keep
      // the stale amount forever.
      queryClient.setQueryData<
        (HarvestSharePlanningRow & Record<string, unknown>)[]
      >(
        getCommissioningHarvestSharePlanningListQueryKey(listParams),
        (old) => {
          if (!old) return old;
          const saved = savedRecord as unknown as HarvestSharePlanningRow &
            Record<string, unknown>;
          if (!old.some((row) => row.id === saved.id)) {
            // Freshly-created slot the cache doesn't know yet — prepend it
            // (EditableTable pins new rows to the top anyway).
            return action === "create" ? [saved, ...old] : old;
          }
          return old.map((row) =>
            row.id === saved.id
              ? {
                  ...(Object.fromEntries(
                    Object.entries(row).filter(
                      ([cellKey]) => !cellKey.startsWith("day_"),
                    ),
                  ) as HarvestSharePlanningRow & Record<string, unknown>),
                  ...saved,
                }
              : row,
          );
        },
      );
    },
    [refetchGranularity, invalidateData, queryClient, listParams],
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
