import { Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import type { TFunction } from "i18next";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCommissioningDeliveryStationToursOverviewRetrieve } from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningDeliveryStationToursOverviewRetrieveParams,
  PackingBoxesMatrixColumn,
  StationOverview,
  TourOverview,
} from "@shared/api/generated/models";
import { DeliveryStationsOverviewPDFGenerator } from "@features/commissioning/pdfs";
import { DaySelector, WeekSelector } from "@shared/selectors";
import { ExplainerText } from "@shared/ui";
import {
  useBoxCombinationColumns,
  useShareDeliveryDays,
} from "@features/commissioning/hooks";
import {
  formatDayLabel,
  formatWeekLabel,
  generatePdfFilename,
  getDayName,
} from "@shared/utils";

const currentYear = dayjs().year();
const currentWeek = dayjs().isoWeek();

// One tour's table: rows = stations, columns = THAT tour's box combinations.
// Each tour carries its own columns (they differ across tours), so the
// combination-column hook runs per tour, inside this child component.
function TourTable({
  tourNumber,
  columns: matrixColumns,
  stations,
  loading,
  t,
}: {
  tourNumber: number;
  columns: PackingBoxesMatrixColumn[];
  stations: StationOverview[];
  loading: boolean;
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
      ...(comboColumns as unknown as ColumnsType<StationOverview>),
    ],
    [comboColumns, t],
  );

  return (
    <div style={{ marginTop: "4em", marginBottom: "2em" }}>
      <h3>{t("commissioning.tour_number", { number: tourNumber })}</h3>
      <Table
        columns={columns}
        dataSource={stations}
        pagination={false}
        size="small"
        loading={loading}
        className="custom-jasmin-table w-max"
        rowKey={(record) => record.delivery_station_day_id}
        bordered
        locale={{
          emptyText: <div style={{ height: "4em" }}>{t("table.no_data")}</div>,
        }}
      />
    </div>
  );
}

export default function DeliveryStationOverview() {
  const [selectedYear, setSelectedYear] = useState(currentYear);
  const [selectedWeek, setSelectedWeek] = useState<number | null>(currentWeek);
  const [selectedDeliveryDay, setSelectedDeliveryDay] = useState<number | null>(
    null,
  );

  const { t } = useTranslation();

  // delivery days
  const [shareDeliveryDaysFilters, setShareDeliveryDaysFilters] = useState({
    active_at_date: dayjs()
      .year(selectedYear)
      .isoWeek(selectedWeek!)
      .isoWeekday(6)
      .format("YYYY-MM-DD"),
  });

  useEffect(() => {
    setShareDeliveryDaysFilters({
      active_at_date: dayjs()
        .year(selectedYear)
        .isoWeek(selectedWeek!)
        .isoWeekday(6)
        .format("YYYY-MM-DD"),
    });
  }, [selectedYear, selectedWeek]);

  const { dayNumbers } = useShareDeliveryDays(shareDeliveryDaysFilters);

  // Select first day by default
  useEffect(() => {
    if (dayNumbers && dayNumbers.length > 0) {
      const validDays = dayNumbers.filter((day) => day !== null) as number[];
      if (validDays.length > 0 && !validDays.includes(selectedDeliveryDay!)) {
        setSelectedDeliveryDay(validDays[0]);
      }
    }
  }, [dayNumbers, selectedDeliveryDay]);

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

  const { data: responseData, isLoading: loading } =
    useCommissioningDeliveryStationToursOverviewRetrieve(queryParams, {
      query: {
        enabled: selectedDeliveryDay !== null,
      },
    });

  // Only tours that actually have box combinations (deliveries) are returned,
  // each with its own columns — iterate them directly.
  const tours = useMemo<TourOverview[]>(
    () => responseData?.tours ?? [],
    [responseData?.tours],
  );

  return (
    <div>
      <h1>{t("commissioning.tour_lists")}</h1>

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

      {/* PDF Download */}
      {tours.length > 0 && !loading && (
        <div style={{ marginTop: "3em" }}>
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

      {tours.map((tour) => (
        <TourTable
          key={tour.tour_number}
          tourNumber={tour.tour_number}
          columns={tour.columns}
          stations={tour.stations}
          loading={loading}
          t={t}
        />
      ))}

      {/* Show message when no tours have deliveries */}
      {tours.length === 0 && !loading && (
        <div style={{ marginTop: "2em", textAlign: "center" }}>
          {t("commissioning.no_tours_available")}
        </div>
      )}

      <ExplainerText title={t("common.info")}>
        {t("explainers.delivery_stations_overview")}
      </ExplainerText>
    </div>
  );
}
