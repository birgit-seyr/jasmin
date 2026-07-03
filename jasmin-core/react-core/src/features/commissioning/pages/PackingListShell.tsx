import { Select } from "antd";
import dayjs from "dayjs";
import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import type {
  CommissioningShareTypesListParams,
  CommissioningSharesDeliveryDaysListParams,
} from "@shared/api/generated/models";
import { DaySelector, ShareTypeSelector, WeekSelector } from '@shared/selectors';
import { DeliveryStationSelector, TourSelector } from '@features/commissioning/selectors';
import { MobileStack } from '@shared/ui';
import { NoVariationColumnsBanner, RelatedDayInfo, VariationsTotalsCard } from '@features/commissioning/components';
import { useDateFormat, useIsMobile, useShareTypes, useTenant } from '@hooks/index';
import { useCurrentDays, useDeliveryStations, usePackingModeShareGroups, useShareContentGranularity, useShareDeliveryDays, useShareTypeVariations, useShareTypeVariationsAmounts } from '@features/commissioning/hooks';
import type { ShareDeliveryDayOption } from "@features/commissioning/hooks/useShareDeliveryDays";
import type { ShareTypeOption } from "@hooks/useShareTypes";
import type { ShareTypeVariationOption } from "@features/commissioning/hooks/useShareTypeVariations";
import { activeAtDateForWeek, formatDayLabel, formatWeekLabel, generatePdfFilename, isWeekInPast } from "@shared/utils";

const { Option } = Select;

const currentYear = dayjs().year();
const currentWeek = dayjs().isoWeek();
const currentDay = dayjs().isoWeekday();

export type PackingListMode = "boxes" | "bulk";

export interface VariationTotal {
  id: string;
  size: string;
  totalQuantity: number;
}

export interface PackingListShellState {
  // Raw filter state
  selectedYear: number;
  selectedWeek: number | null;
  selectedShareType: string | null;
  isPast: boolean;
  selectedDeliveryStation: string | null;
  selectedTour: number | "all";
  selectedPackingStation: number;
  numberPackingStations: number;

  // Derived data
  shareTypes: ShareTypeOption[];
  shareTypesCount: number;
  shareTypeVariations: ShareTypeVariationOption[];
  selectedDeliveryDay: number | null;
  packingDaysForDelivery: number[];
  getDeliveryDayId: string | null;
  hasMultipleToursForSelectedDay: boolean;
  // The tour to filter packing data by, or undefined for "all tours".
  // Resolves to undefined whenever tour isn't an active granularity
  // dimension (the tour selector is hidden) — so a stuck default
  // selectedTour never silently hides other tours' deliveries.
  effectiveTour: number | undefined;
  variationsTotals: VariationTotal[];
  variationsTotalsFilters: Record<string, unknown>;

  // Helpers
  calculatePackingDate: (packingDayNum: number | null) => string;
  generateFilename: (prefix: string) => string;
  queryEnabled: boolean;
  // Resolves to the first available share_type when there's only one
  effectiveShareType: string;
}

interface PackingListShellProps {
  titleKey: string;
  mode: PackingListMode;
  variationsTotalsTooltipKey?: string;
  children: (state: PackingListShellState) => ReactNode;
}

/**
 * Shared chrome for the per-box and per-station packing list pages.
 *
 * Owns: week/day/share-type filters, delivery-day resolution, optional
 * tour / packing-station / delivery-station selectors, and the
 * variations-totals card. Each page renders its own table + PDF buttons
 * via the render-prop children, receiving the shell state.
 *
 * Modes:
 * - "boxes" — selectors gated by granularity (per-day vs per-tour vs
 *   per-station). Shows the variations-totals card and the packing-station
 *   select when the tenant has >1 packing station.
 * - "bulk"  — always per-station (granularity is ignored). No tour, no
 *   packing-station, no variations-totals card. Auto-selects the first
 *   delivery station on mount.
 */
export default function PackingListShell({
  titleKey,
  mode,
  variationsTotalsTooltipKey,
  children,
}: PackingListShellProps) {
  const [selectedYear, setSelectedYear] = useState(currentYear);
  const [selectedWeek, setSelectedWeek] = useState<number | null>(currentWeek);
  const [selectedDeliveryDay, setSelectedDeliveryDay] = useState<number | null>(
    currentDay - 1,
  );
  const isPast = useMemo(
    () => isWeekInPast(selectedYear, selectedWeek),
    [selectedYear, selectedWeek],
  );
  const [selectedTour, setSelectedTour] = useState<number | "all">(1);
  const [selectedDeliveryStation, setSelectedDeliveryStation] = useState<
    string | null
  >(null);
  const [selectedShareType, setSelectedShareType] = useState<string | null>(
    null,
  );
  const [selectedPackingStation, setSelectedPackingStation] = useState(1);

  const { t } = useTranslation();
  const { getSetting } = useTenant();
  const { dateFormat, mobileDateFormat } = useDateFormat();
  const isMobile = useIsMobile();

  const numberPackingStations = getSetting(
    "number_packing_stations",
    2,
  ) as number;

  const packingStationOptions = useMemo(
    () =>
      Array.from({ length: numberPackingStations }, (_, index) => ({
        value: index + 1,
        label: t("commissioning.packing_station_number", { number: index + 1 }),
      })),
    [numberPackingStations, t],
  );

  const granularParams = useMemo(
    () => ({
      year: selectedYear,
      delivery_week: selectedWeek ?? undefined,
      // Scope granularity to the displayed share_type so a simple share
      // (honey) isn't judged by a complex harvest share's per-station
      // amounts. Drives the correct day/tour/station selectors per share.
      share_type: selectedShareType ?? undefined,
      // Scope to the SELECTED delivery day so the boxes station-gate reflects
      // that day's per-station consistency, not a global across-all-days result.
      day_number: selectedDeliveryDay ?? undefined,
    }),
    [selectedYear, selectedWeek, selectedShareType, selectedDeliveryDay],
  );

  // Bulk is always per-station, so granularity is irrelevant there.
  const { daysOk, toursOk } = useShareContentGranularity(
    mode === "boxes" ? granularParams : {},
  );

  const shareTypeParams = useMemo<CommissioningShareTypesListParams>(
    () => ({ active_at_date: activeAtDateForWeek(selectedYear, selectedWeek) }),
    [selectedYear, selectedWeek],
  );

  // Scope the share-type selector to this page's packing mode: PackingListBulk
  // only shows share types with a bulk-packed variation, PackingListBoxes only
  // boxed ones. Same ``active_at_date`` as ``shareTypeParams`` → the underlying
  // queries are cache-shared, not re-fetched.
  const { shareTypes: allShareTypes } = useShareTypes(shareTypeParams);
  const { bulkShareTypeIds, boxesShareTypeIds } = usePackingModeShareGroups(
    activeAtDateForWeek(selectedYear, selectedWeek),
  );
  const matchingShareTypeIds =
    mode === "bulk" ? bulkShareTypeIds : boxesShareTypeIds;
  const shareTypes = useMemo(
    () => allShareTypes.filter((st) => !!st.id && matchingShareTypeIds.has(st.id)),
    [allShareTypes, matchingShareTypeIds],
  );
  const shareTypesCount = shareTypes.length;

  const shareTypeVariationFilters = useMemo(
    () => ({
      physical: true,
      active_at_date: activeAtDateForWeek(selectedYear, selectedWeek),
      share_type: selectedShareType ?? undefined,
    }),
    [selectedYear, selectedWeek, selectedShareType],
  );

  const { shareTypeVariations, loading: shareTypeVariationsLoading } =
    useShareTypeVariations(shareTypeVariationFilters);

  const shareDeliveryDaysParams = useMemo<CommissioningSharesDeliveryDaysListParams>(
    () => ({ active_at_date: activeAtDateForWeek(selectedYear, selectedWeek) }),
    [selectedYear, selectedWeek],
  );

  const { shareDeliveryDays } = useShareDeliveryDays(shareDeliveryDaysParams);

  const { getRelatedDays, isLoaded } = useCurrentDays(
    selectedWeek ?? undefined,
    selectedYear,
  );

  // Reconcile the share-type pick against the share types available for the
  // current year/week: keep it if it's still offered, only fall back to the
  // first when it's genuinely gone. This (plus ShareTypeSelector's
  // preserveSelection) is the whole story — there is deliberately NO
  // unconditional "reset to null on year/week change" effect, because that
  // made a still-valid pick spring back to the first share type every time
  // the user changed the week.
  useEffect(() => {
    if (shareTypes && shareTypes.length > 0) {
      const validShareTypeIds = shareTypes.map((st: ShareTypeOption) => st.id);
      if (
        selectedShareType === null ||
        !validShareTypeIds.includes(selectedShareType)
      ) {
        setSelectedShareType(shareTypes[0].id ?? null);
      }
    }
  }, [shareTypes, selectedShareType]);

  // The user picks the DELIVERY day; the packing day(s) for it are derived for
  // display (one delivery day can map to one or more packing days).
  const packingDaysForDelivery = useMemo<number[]>(() => {
    if (
      !isLoaded ||
      selectedDeliveryDay === null ||
      !getRelatedDays?.getPackingDaysForDelivery
    ) {
      return [];
    }
    return getRelatedDays.getPackingDaysForDelivery(selectedDeliveryDay);
  }, [isLoaded, getRelatedDays, selectedDeliveryDay]);

  // The day selector lists only the tenant's ACTUAL delivery weekdays (not all
  // seven), matching CommissioningListPacking's delivery-day selector.
  const deliveryDayOptions = useMemo<number[]>(
    () =>
      Array.from(
        new Set(shareDeliveryDays.map((day) => Number(day.day_number))),
      ).sort((a, b) => a - b),
    [shareDeliveryDays],
  );

  // Keep the selection on a real delivery day: if the default (today's weekday)
  // or a stale pick isn't an actual delivery day, snap to the first one.
  useEffect(() => {
    if (deliveryDayOptions.length === 0) return;
    if (
      selectedDeliveryDay !== null &&
      deliveryDayOptions.includes(selectedDeliveryDay)
    ) {
      return;
    }
    setSelectedDeliveryDay(deliveryDayOptions[0]);
  }, [deliveryDayOptions, selectedDeliveryDay]);

  const getDeliveryDayId = useMemo<string | null>(() => {
    if (selectedDeliveryDay === null || !shareDeliveryDays.length) return null;
    const deliveryDay = shareDeliveryDays.find(
      (day: ShareDeliveryDayOption) =>
        Number(day.day_number) === Number(selectedDeliveryDay),
    );
    return deliveryDay?.id ?? null;
  }, [selectedDeliveryDay, shareDeliveryDays]);

  const hasMultipleToursForSelectedDay = useMemo(() => {
    if (selectedDeliveryDay === null || !shareDeliveryDays.length) return false;
    const dayRecord = shareDeliveryDays.find(
      (day: ShareDeliveryDayOption) =>
        Number(day.day_number) === Number(selectedDeliveryDay),
    );
    return dayRecord
      ? (((dayRecord as unknown as Record<string, unknown>)
          .number_of_tours as number) || 1) > 1
      : false;
  }, [selectedDeliveryDay, shareDeliveryDays]);

  // The tour filter is meaningful ONLY while the user can actually pick a
  // tour — i.e. exactly when the tour selector is rendered. This is the same
  // condition as ``showTourSelector`` below (kept in one place so the two
  // can't drift). When the selector is hidden, ``selectedTour`` is stuck at
  // its default of 1 and unchangeable, so filtering by it would silently
  // drop every delivery on another tour (e.g. a honey share whose only
  // demand sits on tour 2).
  const tourSelectorActive =
    mode === "boxes" &&
    !isMobile &&
    !daysOk &&
    toursOk &&
    hasMultipleToursForSelectedDay;

  // Tour to filter packing data by, or undefined for "all tours". Honour an
  // explicit pick only while the selector is live; otherwise show all tours
  // so both the recipe table and the totals card see the full picture.
  const effectiveTour = useMemo<number | undefined>(() => {
    if (!tourSelectorActive || selectedTour === "all") return undefined;
    return selectedTour;
  }, [tourSelectorActive, selectedTour]);

  // Bulk mode defaults to the first active delivery station once the
  // list loads — keeps the table populated on first paint without
  // forcing the user through an explicit picker.
  const { deliveryStations: bulkStations } = useDeliveryStations({
    delivery_day: mode === "bulk" ? (getDeliveryDayId ?? undefined) : undefined,
  });

  useEffect(() => {
    if (mode !== "bulk") return;
    if (selectedDeliveryStation !== null) return;
    if (bulkStations.length === 0) return;
    setSelectedDeliveryStation(bulkStations[0].value);
  }, [mode, selectedDeliveryStation, bulkStations]);

  // If the currently selected station disappears from the active list
  // (e.g. the user switches weeks and that station is no longer scheduled),
  // drop it so the auto-default can pick a valid one again.
  useEffect(() => {
    if (mode !== "bulk") return;
    if (selectedDeliveryStation === null) return;
    if (bulkStations.length === 0) return;
    const stillValid = bulkStations.some(
      (s) => s.value === selectedDeliveryStation,
    );
    if (!stillValid) setSelectedDeliveryStation(null);
  }, [mode, selectedDeliveryStation, bulkStations]);

  const variationsTotalsFilters = useMemo(
    () => ({
      year: selectedYear,
      delivery_week: selectedWeek ?? currentWeek,
      delivery_day: getDeliveryDayId ?? undefined,
      tour: effectiveTour,
      delivery_station: selectedDeliveryStation ?? undefined,
      share_type: selectedShareType ?? undefined,
      sending_share_type_id: true,
      physical_share_type_variations: true,
    }),
    [
      selectedYear,
      selectedWeek,
      getDeliveryDayId,
      effectiveTour,
      selectedDeliveryStation,
      selectedShareType,
    ],
  );

  // Only boxes mode actually needs the per-variation totals payload
  // (for the PDF generator); bulk doesn't render it.
  const { variationsTotals: rawVariationsTotals } = useShareTypeVariationsAmounts(
    mode === "boxes" ? variationsTotalsFilters : {},
  );

  const variationsTotals = useMemo<VariationTotal[]>(
    () => (rawVariationsTotals as unknown as VariationTotal[]) ?? [],
    [rawVariationsTotals],
  );

  const calculatePackingDate = useCallback(
    (packingDayNum: number | null) => {
      if (packingDayNum === null) return "";
      const deliveryDays =
        getRelatedDays?.getDeliveryDaysForPacking(packingDayNum) || [];
      const deliveryDay = deliveryDays[0];
      const dayIso = packingDayNum + 1;
      let date = dayjs()
        .year(selectedYear)
        .isoWeek(selectedWeek ?? currentWeek)
        .isoWeekday(dayIso);
      if (deliveryDay !== undefined && packingDayNum > deliveryDay) {
        date = date.subtract(1, "week");
      }
      return isMobile
        ? date.format(`dd, ${mobileDateFormat}`)
        : date.format(`dddd, ${dateFormat}`);
    },
    [
      selectedYear,
      selectedWeek,
      getRelatedDays,
      isMobile,
      dateFormat,
      mobileDateFormat,
    ],
  );

  // The delivery date is simply the delivery weekday within the selected week
  // (no packing-vs-delivery week shift) — used as the day-selector's date.
  const calculateDeliveryDate = useCallback(
    (deliveryDayNum: number | null) => {
      if (deliveryDayNum === null) return "";
      const date = dayjs()
        .year(selectedYear)
        .isoWeek(selectedWeek ?? currentWeek)
        .isoWeekday(deliveryDayNum + 1);
      return isMobile
        ? date.format(`dd, ${mobileDateFormat}`)
        : date.format(`dddd, ${dateFormat}`);
    },
    [selectedYear, selectedWeek, isMobile, dateFormat, mobileDateFormat],
  );

  const generateFilename = useCallback(
    (prefix: string) =>
      generatePdfFilename([
        prefix,
        selectedYear,
        formatWeekLabel(selectedWeek, t),
        formatDayLabel(selectedDeliveryDay, t),
      ]),
    [selectedYear, selectedWeek, selectedDeliveryDay, t],
  );

  const effectiveShareType =
    (shareTypesCount > 1 ? selectedShareType : shareTypes[0]?.value) ?? "";

  // Granularity is a PackingListBoxes concern only (the hook is only queried in
  // boxes mode). When the share's per-station amounts are neither day- nor
  // tour-consistent, the all-stations view would collapse divergent amounts, so
  // the office must pick a station first (the backend refuses the unscoped
  // request). Bulk is always per-station and keeps its own station requirement
  // below — granularity never applies to it.
  const boxesNeedsStation =
    mode === "boxes" && !isMobile && !daysOk && !toursOk;

  const queryEnabled =
    selectedDeliveryDay !== null &&
    selectedShareType !== null &&
    (mode !== "bulk" || selectedDeliveryStation !== null) &&
    (!boxesNeedsStation || selectedDeliveryStation !== null) &&
    // No share-type variations → no packing columns; the body shows the banner
    // instead, so don't fetch the (empty) packing data.
    shareTypeVariations.length > 0;

  // Same condition that makes ``effectiveTour`` honour the picked tour.
  const showTourSelector = tourSelectorActive;

  const showStationSelector = mode === "bulk" || boxesNeedsStation;

  const showPackingStationSelect =
    mode === "boxes" && !isMobile && numberPackingStations > 1;

  const showVariationsTotalsCard = mode === "boxes";

  const state: PackingListShellState = {
    selectedYear,
    selectedWeek,
    selectedShareType,
    isPast,
    selectedDeliveryStation,
    selectedTour,
    selectedPackingStation,
    numberPackingStations,
    shareTypes: shareTypes as ShareTypeOption[],
    shareTypesCount,
    shareTypeVariations: shareTypeVariations as ShareTypeVariationOption[],
    selectedDeliveryDay,
    packingDaysForDelivery,
    getDeliveryDayId,
    hasMultipleToursForSelectedDay,
    effectiveTour,
    variationsTotals,
    variationsTotalsFilters,
    calculatePackingDate,
    generateFilename,
    queryEnabled,
    effectiveShareType: effectiveShareType as string,
  };

  return (
    <div>
      <h1>{t(titleKey)}</h1>

      <MobileStack>
        <WeekSelector
          selectedYear={selectedYear}
          setSelectedYear={setSelectedYear}
          selectedWeek={selectedWeek}
          setSelectedWeek={setSelectedWeek}
        />

        <DaySelector
          selectedDay={selectedDeliveryDay}
          setSelectedDay={setSelectedDeliveryDay}
          selectedWeek={selectedWeek ?? currentWeek}
          selectedYear={selectedYear}
          days={deliveryDayOptions}
          suffix={t("commissioning.delivery_day")}
          customDateCalculator={calculateDeliveryDate}
        />

        <ShareTypeSelector
          selectedShareType={selectedShareType}
          setSelectedShareType={setSelectedShareType}
          year={selectedYear}
          delivery_week={selectedWeek ?? undefined}
          allowedShareTypeIds={matchingShareTypeIds}
        />
      </MobileStack>

      {!isMobile && (
        <div>
          <RelatedDayInfo
            label={t("commissioning.packing_day")}
            relatedDayNumbers={packingDaysForDelivery}
            selectedWeek={selectedWeek ?? currentWeek}
            selectedYear={selectedYear}
            formatDate={calculatePackingDate}
          />
        </div>
      )}

      {showTourSelector && (
        <TourSelector
          selectedTour={selectedTour}
          setSelectedTour={setSelectedTour}
          delivery_day={getDeliveryDayId}
          selectedYear={selectedYear}
          selectedWeek={selectedWeek}
        />
      )}

      {showStationSelector && (
        <div
          style={{
            marginTop: "1em",
            marginLeft: "-2em",
            marginBottom: "1em",
          }}
        >
          <DeliveryStationSelector
            selectedDeliveryStation={selectedDeliveryStation}
            setSelectedDeliveryStation={setSelectedDeliveryStation}
            delivery_day={getDeliveryDayId}
          />
        </div>
      )}

      {showPackingStationSelect && (
        <div style={{ marginTop: "1em", marginBottom: "1em" }}>
          <Select
            value={selectedPackingStation}
            style={{ width: "12em" }}
            size="small"
            onChange={setSelectedPackingStation}
            placeholder={t("commissioning.select_packing_station")}
            className="bold-select week-selector-select"
          >
            {packingStationOptions.map((station) => (
              <Option key={station.value} value={station.value}>
                {station.label}
              </Option>
            ))}
          </Select>
        </div>
      )}

      {showVariationsTotalsCard && (
        <VariationsTotalsCard
          filters={variationsTotalsFilters}
          tooltip={
            variationsTotalsTooltipKey
              ? t(variationsTotalsTooltipKey)
              : undefined
          }
        />
      )}

      {/* No share-type variations → the packing grid's dynamic columns would
          be empty; show a configuration hint instead of an empty table. While
          the variations query is still loading, fall through to the body so it
          can render its own loading spinner. */}
      {!shareTypeVariationsLoading && shareTypeVariations.length === 0 ? (
        <NoVariationColumnsBanner />
      ) : (
        children(state)
      )}
    </div>
  );
}
