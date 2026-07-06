import { Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCommissioningDeliveryStationToursOverviewRetrieve } from "@shared/api/generated/commissioning/commissioning";
import type { CommissioningDeliveryStationToursOverviewRetrieveParams } from "@shared/api/generated/models";
import type { StationOverview } from "@shared/api/generated/models";
import { DeliveryStationsOverviewPDFGenerator } from "@features/commissioning/pdfs";
import { DaySelector, WeekSelector } from "@shared/selectors";
import { ExplainerText } from "@shared/ui";
import {
  useShareDeliveryDays,
  useShareTypeVariations,
} from "@features/commissioning/hooks";
import type { ShareTypeVariationOption } from "@features/commissioning/hooks/useShareTypeVariations";
import {
  formatDayLabel,
  formatWeekLabel,
  generatePdfFilename,
  getDayName,
} from "@shared/utils";

const currentYear = dayjs().year();
const currentWeek = dayjs().isoWeek();

interface VariationGroup {
  share_type_id: string;
  share_type_name: string;
  variations: ShareTypeVariationOption[];
}

export default function DeliveryStationOverview() {
  const [selectedYear, setSelectedYear] = useState(currentYear);
  const [selectedWeek, setSelectedWeek] = useState<number | null>(currentWeek);
  const [selectedDeliveryDay, setSelectedDeliveryDay] = useState<number | null>(
    null,
  );

  const { t } = useTranslation();

  // Fetch active share type variations for the selected week
  const shareTypeVariationFilters = useMemo(
    () => ({
      active_at_date: dayjs()
        .year(selectedYear)
        .isoWeek(selectedWeek!)
        .isoWeekday(selectedDeliveryDay !== null ? selectedDeliveryDay + 1 : 6)
        .format("YYYY-MM-DD"),
    }),
    [selectedYear, selectedWeek, selectedDeliveryDay],
  );

  const { shareTypeVariations } = useShareTypeVariations(
    shareTypeVariationFilters,
  );

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

  // Get number of tours
  const numberOfTours = responseData?.number_of_tours ?? 0;

  // Creating an array of tour numbers for mapping
  const tourNumbers = useMemo(
    () => Array.from({ length: numberOfTours }, (_, index) => index + 1),
    [numberOfTours],
  );

  // Group variations by share_type
  const groupedVariations = useMemo<VariationGroup[]>(() => {
    const groups: Record<string, VariationGroup> = {};

    shareTypeVariations.forEach((variation) => {
      const shareTypeId = variation.share_type;
      const shareTypeName = variation.share_type_name ?? "";

      if (!groups[shareTypeId]) {
        groups[shareTypeId] = {
          share_type_id: shareTypeId,
          share_type_name: shareTypeName,
          variations: [],
        };
      }

      groups[shareTypeId].variations.push(variation);
    });

    return Object.values(groups);
  }, [shareTypeVariations]);

  const columns = useMemo<ColumnsType<StationOverview>>(() => {
    const baseColumns: ColumnsType<StationOverview> = [
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
    ];

    // Create grouped columns for each share type
    const variationColumns = groupedVariations.map((group) => {
      // Create parent column with children
      return {
        title: group.share_type_name,
        key: `share_type_${group.share_type_id}`,
        align: "center" as const,
        className: "column-group-start",
        children: group.variations.map((variation, idx) => ({
          title: t(`commissioning.${variation.size}`),
          dataIndex: `variation_${variation.id}`,
          key: `variation_${variation.id}`,
          align: "center" as const,
          width: "6em",
          ...(idx === 0 && { className: "column-group-start" }),
          render: (value: number | null) => value || 0,
        })),
      };
    });

    return [...baseColumns, ...variationColumns];
  }, [groupedVariations, t]);

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
      {numberOfTours > 0 && !loading && (
        <div style={{ marginTop: "3em" }}>
          <DeliveryStationsOverviewPDFGenerator
            tours={
              responseData?.tours
                ?.filter((tour) => (tour.stations?.length ?? 0) > 0)
                .map((tour) => ({
                  tour_number: tour.tour_number,
                  stations: tour.stations,
                })) ?? null
            }
            week={selectedWeek!}
            dayName={
              selectedDeliveryDay !== null
                ? getDayName(selectedDeliveryDay, t)
                : ""
            }
            variations={
              shareTypeVariations
                .filter((v) => v.id)
                .map((v) => ({
                  id: v.id!,
                  size: v.size,
                  share_type: v.share_type,
                  share_type_name: v.share_type_name ?? "",
                })) ?? null
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

      {tourNumbers.map((tourNumber) => {
        const tourData = responseData?.tours?.find(
          (tour) => tour.tour_number === tourNumber,
        );
        const stations = tourData?.stations ?? [];

        return (
          <div
            key={tourNumber}
            style={{ marginTop: "4em", marginBottom: "2em" }}
          >
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
                emptyText: (
                  <div style={{ height: "4em" }}>{t("table.no_data")}</div>
                ),
              }}
            />
          </div>
        );
      })}

      {/* Show message when no tours available */}
      {numberOfTours === 0 && !loading && (
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
