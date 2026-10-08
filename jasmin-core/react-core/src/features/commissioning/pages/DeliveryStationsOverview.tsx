import {
  useBoxCombinationColumns,
  useShareDeliveryDays,
  useShareTypeVariations,
} from "@features/commissioning/hooks";
import { DeliveryStationsOverviewPDFGenerator } from "@features/commissioning/pdfs";
import { filterBulkComboColumns } from "@features/commissioning/utils/filterBulkComboColumns";
import {
  useNumberFormat,
  useShareTypeVariationSizeOptions,
  useTenant,
  useYearWeekState,
} from "@hooks/index";
import { useCommissioningDeliveryStationToursOverviewRetrieve } from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningDeliveryStationToursOverviewRetrieveParams,
  PackingBoxesMatrixColumn,
  ShareTypeVariationMetadata,
  StationOverview,
  TourOverview,
} from "@shared/api/generated/models";
import { DaySelector, WeekSelector } from "@shared/selectors";
import { EmptyHint, ExplainerText, PastWarningMessage } from "@shared/ui";
import {
  activeAtDateForWeek,
  formatDayLabel,
  formatWeekLabel,
  generatePdfFilename,
  getDayName,
} from "@shared/utils";
import { Spin, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { TFunction } from "i18next";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

/** A station's count under one column key; the generated type leaves those keys out. */
const countAt = (station: StationOverview, key: string) =>
  Number((station as unknown as Record<string, unknown>)[key]);

// Flat per-variation columns (grouped by share type) for import-shares tenants:
// they have no box combinations, so the tour table shows one column per active
// share_type_variation. Each cell is that variation's box count at the station
// (the demand-service-backed ``variation_<id>`` value, which works in both modes).
function useVariationColumns(
  variations: ShareTypeVariationMetadata[],
): ColumnsType<StationOverview> {
  const { format } = useNumberFormat();
  const { getShareTypeVariationSizeLabel } = useShareTypeVariationSizeOptions();

  return useMemo(() => {
    const groups = new Map<
      string,
      { name: string; vars: ShareTypeVariationMetadata[] }
    >();
    for (const variation of variations) {
      const group = groups.get(variation.share_type_id) ?? {
        name: variation.share_type_name,
        vars: [],
      };
      group.vars.push(variation);
      groups.set(variation.share_type_id, group);
    }
    return [...groups.values()].map((group) => ({
      title: group.name,
      align: "center" as const,
      children: group.vars.map((variation) => ({
        title: variation.size
          ? getShareTypeVariationSizeLabel(variation.size)
          : variation.display_name,
        dataIndex: variation.key,
        key: variation.key,
        align: "center" as const,
        width: "5em",
        render: (value: unknown) => {
          const count = Number(value);
          return Number.isFinite(count) && count !== 0 ? format(count, 0) : "";
        },
      })),
    }));
  }, [variations, format, getShareTypeVariationSizeLabel]);
}

/**
 * The tours that still deliver once the bulk-packed share sizes are left out:
 * a box tour keeps only its other kinds of box, and a tour left with none —
 * or, for a farm that uploads its share amounts, with no share of another
 * size at any of its stations — is dropped from the screen and the PDF alike.
 */
function toursWithoutBulk(
  tours: TourOverview[],
  bulkVariationIds: ReadonlySet<string>,
  variations: ShareTypeVariationMetadata[],
  usesExternalDemand: boolean,
): TourOverview[] {
  if (usesExternalDemand) {
    return tours.filter((tour) =>
      tour.stations.some((station) =>
        variations.some((variation) => {
          const count = countAt(station, variation.key);
          return Number.isFinite(count) && count !== 0;
        }),
      ),
    );
  }
  return tours
    .map((tour) => ({
      ...tour,
      columns: filterBulkComboColumns(tour.columns, bulkVariationIds),
    }))
    .filter((tour) => tour.columns.length > 0);
}

// One tour's table: rows = stations, columns = THAT tour's box combinations.
// Each tour carries its own columns (they differ across tours), so the
// combination-column hook runs per tour, inside this child component.
function TourTable({
  tourNumber,
  columns: matrixColumns,
  stations,
  variationColumns,
  usesExternalDemand,
  t,
}: {
  tourNumber: number;
  columns: PackingBoxesMatrixColumn[];
  stations: StationOverview[];
  variationColumns: ColumnsType<StationOverview>;
  usesExternalDemand: boolean;
  t: TFunction;
}) {
  const comboColumns = useBoxCombinationColumns(matrixColumns);

  const columns = useMemo<ColumnsType<StationOverview>>(
    () => [
      {
        title: t("commissioning.delivery_station"),
        dataIndex: "delivery_station_short_name",
        key: "delivery_station_short_name",
        align: "left",
        width: "12em",
        fixed: "left",
        render: (text: string, record: StationOverview) => (
          <strong>{text || record.delivery_station_name || "-"}</strong>
        ),
      },
      // Import tenants have no combinations → show flat per-variation columns.
      ...(usesExternalDemand
        ? variationColumns
        : (comboColumns as unknown as ColumnsType<StationOverview>)),
    ],
    [comboColumns, usesExternalDemand, variationColumns, t],
  );

  return (
    <div className="delivery-stations-overview__tour">
      <h3>{t("commissioning.tour_number", { number: tourNumber })}</h3>
      <Table
        columns={columns}
        dataSource={stations}
        pagination={false}
        size="small"
        className="custom-jasmin-table w-max"
        rowKey="delivery_station_day_id"
        bordered
        locale={{ emptyText: <EmptyHint>{t("table.no_data")}</EmptyHint> }}
      />
    </div>
  );
}

export default function DeliveryStationsOverview() {
  const { selectedYear, setSelectedYear, selectedWeek, setSelectedWeek } =
    useYearWeekState();
  const [selectedDeliveryDay, setSelectedDeliveryDay] = useState<number | null>(
    null,
  );

  const { t } = useTranslation();
  const { getSetting } = useTenant();
  const usesExternalDemand = getSetting(
    "uploads_weekly_share_amount",
    false,
  ) as boolean;

  // Derived in the same render as the week, so the days listed are never
  // another week's.
  const shareDeliveryDaysFilters = useMemo(
    () => ({ active_at_date: activeAtDateForWeek(selectedYear, selectedWeek) }),
    [selectedYear, selectedWeek],
  );

  const {
    dayNumbers,
    pending: daysPending,
    noDaysListed: weekHasNoDays,
    error: daysError,
  } = useShareDeliveryDays(shareDeliveryDaysFilters);

  // Once the week's days are in, the pick is one of them: a listed pick stays,
  // anything else becomes the first day, and a week without days leaves none.
  useEffect(() => {
    if (daysPending) return;
    if (dayNumbers.length === 0) {
      if (selectedDeliveryDay !== null) setSelectedDeliveryDay(null);
      return;
    }
    if (!dayNumbers.some((day) => day === selectedDeliveryDay)) {
      setSelectedDeliveryDay(dayNumbers[0]);
    }
  }, [dayNumbers, daysPending, selectedDeliveryDay]);

  // A day picked in another week stays picked until this week's days arrive
  // and may not be one of them, so the tours are asked for only once it is.
  const dayInWeek =
    selectedDeliveryDay !== null &&
    dayNumbers.some((day) => day === selectedDeliveryDay);

  // The retrieve-params type marks year/delivery_week/day_number as
  // required. We always return a fully-typed object (with 0 placeholders
  // when not ready) and gate the actual request with `enabled` below.
  const queryParams =
    useMemo<CommissioningDeliveryStationToursOverviewRetrieveParams>(
      () => ({
        year: selectedYear,
        delivery_week: selectedWeek ?? 0,
        day_number: selectedDeliveryDay ?? 0,
      }),
      [selectedYear, selectedWeek, selectedDeliveryDay],
    );

  const {
    data: responseData,
    isSuccess: toursLoaded,
    isError: toursFailed,
  } = useCommissioningDeliveryStationToursOverviewRetrieve(queryParams, {
    query: { enabled: dayInWeek && selectedWeek != null },
  });

  // Day-wide variation metadata (import tenants render these as flat columns).
  const rawVariations = useMemo<ShareTypeVariationMetadata[]>(
    () => responseData?.variations ?? [],
    [responseData?.variations],
  );

  // Bulk-packed variations belong on the bulk packing list, not the tour /
  // delivery box lists — hide them here. The tour metadata carries no
  // ``is_packed_bulk`` flag, so we look it up from the variations list
  // (frontend-only filter) and drop those ids from the flat columns.
  const { shareTypeVariations: bulkVariations, loading: bulkLoading } =
    useShareTypeVariations({ is_packed_bulk: true });
  const bulkVariationIds = useMemo(
    () => new Set(bulkVariations.map((variation) => String(variation.id))),
    [bulkVariations],
  );
  const variations = useMemo<ShareTypeVariationMetadata[]>(
    () => rawVariations.filter((v) => !bulkVariationIds.has(String(v.id))),
    [rawVariations, bulkVariationIds],
  );
  const variationColumns = useVariationColumns(variations);

  // The bulk filter runs before a tour counts as delivering, so the on-screen
  // tables and the PDF both see only the tours left with something to deliver.
  const tours = useMemo<TourOverview[]>(
    () =>
      toursWithoutBulk(
        responseData?.tours ?? [],
        bulkVariationIds,
        variations,
        usesExternalDemand,
      ),
    [responseData?.tours, bulkVariationIds, variations, usesExternalDemand],
  );

  const showTours = dayInWeek && toursLoaded && !bulkLoading;
  // A failed load is reported by the app's error toast, not as an empty day.
  const showSpinner =
    !showTours && !weekHasNoDays && !daysError && !toursFailed;

  return (
    <div>
      <h1>{t("commissioning.tour_lists")}</h1>
      <p className="page-subtitle">{t("commissioning.tour_lists_subtitle")}</p>

      <WeekSelector
        selectedYear={selectedYear}
        setSelectedYear={setSelectedYear}
        selectedWeek={selectedWeek}
        setSelectedWeek={setSelectedWeek}
      />

      <DaySelector
        selectedDay={selectedDeliveryDay}
        setSelectedDay={setSelectedDeliveryDay}
        selectedWeek={selectedWeek!}
        selectedYear={selectedYear}
        days={dayNumbers}
        suffix={t("commissioning.delivery_day")}
      />

      {/* PDF Download — combination-based, so only for subscription tenants
          (import tenants have no combos; the on-page flat view covers them). */}
      {showTours && tours.length > 0 && !usesExternalDemand && (
        <div className="delivery-stations-overview__pdf">
          <DeliveryStationsOverviewPDFGenerator
            tours={tours.map((tour) => ({
              tour_number: tour.tour_number,
              columns: tour.columns,
              stations: tour.stations,
            }))}
            week={selectedWeek!}
            dayName={
              selectedDeliveryDay !== null
                ? getDayName(selectedDeliveryDay, t)
                : ""
            }
            filename={generatePdfFilename([
              t("commissioning.deliveries_overview"),
              selectedYear,
              formatWeekLabel(selectedWeek, t),
              formatDayLabel(selectedDeliveryDay, t),
            ])}
            buttonText={t("download.deliveries_overview")}
            t={t}
          />
        </div>
      )}

      {showTours &&
        tours.map((tour) => (
          <TourTable
            key={tour.tour_number}
            tourNumber={tour.tour_number}
            columns={tour.columns}
            stations={tour.stations}
            variationColumns={variationColumns}
            usesExternalDemand={usesExternalDemand}
            t={t}
          />
        ))}

      {showTours && tours.length === 0 && (
        <PastWarningMessage>
          {t("commissioning.packing_list_no_columns")}
        </PastWarningMessage>
      )}

      {weekHasNoDays && (
        <EmptyHint>{t("commissioning.no_delivery_days_in_week")}</EmptyHint>
      )}

      {showSpinner && (
        <div className="flex-center">
          <Spin />
        </div>
      )}

      <ExplainerText title={t("common.info")}>
        {t("explainers.delivery_stations_overview")}
      </ExplainerText>
    </div>
  );
}
