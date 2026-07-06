import { useQueries } from "@tanstack/react-query";
import { Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  getCommissioningShareDeliveryDetailsListQueryOptions,
  useCommissioningShareDeliveryDetailsList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningShareDeliveryDetailsListParams,
  ShareDeliveryDetailsRow,
} from "@shared/api/generated/models";
import { DeliveryStationDetailsPDFGenerator } from "@features/commissioning/pdfs";
import { DaySelector, WeekSelector } from "@shared/selectors";
import { DeliveryStationSelector } from "@features/commissioning/selectors";
import { ExplainerText, ToolTipIcon } from "@shared/ui";
import { useTenant } from "@hooks/index";
import {
  useDeliveryStations,
  useShareDeliveryDays,
  useShareTypeVariationColumns,
} from "@features/commissioning/hooks";
import {
  formatDayLabel,
  formatWeekLabel,
  generatePdfFilename,
  getDayName,
} from "@shared/utils";

const currentYear = dayjs().year();
const currentWeek = dayjs().isoWeek();

export default function DeliveryStationDetails() {
  const [selectedYear, setSelectedYear] = useState(currentYear);
  const [selectedWeek, setSelectedWeek] = useState<number | null>(currentWeek);
  const [selectedDeliveryDay, setSelectedDeliveryDay] = useState<number | null>(
    null,
  );
  const [selectedDeliveryStation, setSelectedDeliveryStation] = useState<
    string | null
  >(null);

  const { t } = useTranslation();
  const { tenantName, logoUrl, tenant } = useTenant();

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

  // Shared hook builds the parent → child variation column tree AND fetches
  // the active variations for the selected day. Also used by
  // `DefaultShareArticlesInShare` so the visual rhythm is identical.
  const { variations: shareTypeVariations, variationColumns } =
    useShareTypeVariationColumns({
      filters: shareTypeVariationFilters,
      width: "8em",
    });

  // delivery days — derived purely from the selected year/week (no effect).
  const shareDeliveryDaysFilters = useMemo(
    () => ({
      active_at_date: dayjs()
        .year(selectedYear)
        .isoWeek(selectedWeek!)
        .isoWeekday(6)
        .format("YYYY-MM-DD"),
    }),
    [selectedYear, selectedWeek],
  );

  const { shareDeliveryDays, dayNumbers } = useShareDeliveryDays(
    shareDeliveryDaysFilters,
  );

  // Select the first valid day when dayNumbers change
  useEffect(() => {
    if (dayNumbers && dayNumbers.length > 0) {
      const validDays = dayNumbers.filter((day) => day !== null) as number[];
      if (validDays.length > 0 && !validDays.includes(selectedDeliveryDay!)) {
        setSelectedDeliveryDay(validDays[0]);
      }
    }
  }, [dayNumbers, selectedDeliveryDay]);

  const isQueryEnabled =
    selectedDeliveryDay !== null && selectedDeliveryStation !== null;

  // The list-params type marks year/delivery_week/day_number as required,
  // but until the user picks a day/station we shouldn't fire. We still
  // return a fully-typed object (with 0 placeholders when not ready) and
  // gate the actual request with `enabled: isQueryEnabled` below.
  const queryParams = useMemo<CommissioningShareDeliveryDetailsListParams>(
    () => ({
      year: selectedYear,
      delivery_week: selectedWeek ?? 0,
      day_number: selectedDeliveryDay ?? 0,
      ...(selectedDeliveryStation
        ? { delivery_station: selectedDeliveryStation }
        : {}),
    }),
    [selectedYear, selectedWeek, selectedDeliveryDay, selectedDeliveryStation],
  );

  const { data, isFetching } = useCommissioningShareDeliveryDetailsList(
    queryParams,
    { query: { enabled: isQueryEnabled } },
  );

  const loading = isQueryEnabled && isFetching;
  // Memoize so the empty branch returns a stable reference and downstream
  // memos depending on `tableData` don't reinvalidate on every render.
  const tableData = useMemo(
    () => (isQueryEnabled ? (data ?? []) : []),
    [isQueryEnabled, data],
  );

  // Compute selectedDeliveryDayId early (needed for station selector and bulk PDFs)
  const selectedDeliveryDayId = useMemo(() => {
    if (selectedDeliveryDay === null || selectedDeliveryDay === undefined) {
      return null;
    }
    const deliveryDay = shareDeliveryDays.find(
      (day) => day.day_number === selectedDeliveryDay,
    );
    return deliveryDay?.id ?? null;
  }, [selectedDeliveryDay, shareDeliveryDays]);

  // Fetch all delivery stations for the selected day (for bulk PDFs)
  const { deliveryStations } = useDeliveryStations(
    selectedDeliveryDayId ? { delivery_day: selectedDeliveryDayId } : {},
  );

  // Bulk fetch: all stations for the selected day (only when table has data)
  const allStationsDayQueries = useQueries({
    queries:
      tableData.length > 0 &&
      selectedDeliveryDay !== null &&
      deliveryStations.length > 0
        ? deliveryStations.map((station) =>
            getCommissioningShareDeliveryDetailsListQueryOptions({
              year: selectedYear,
              delivery_week: selectedWeek!,
              day_number: selectedDeliveryDay,
              delivery_station: station.value,
            }),
          )
        : [],
  });

  // Bulk fetch: all stations for all days in the week (only when table has data)
  const allStationsWeekQueries = useQueries({
    queries:
      tableData.length > 0 &&
      dayNumbers.length > 0 &&
      deliveryStations.length > 0
        ? dayNumbers
            .filter((d) => d !== null)
            .flatMap((dayNum) =>
              deliveryStations.map((station) =>
                getCommissioningShareDeliveryDetailsListQueryOptions({
                  year: selectedYear,
                  delivery_week: selectedWeek!,
                  day_number: dayNum,
                  delivery_station: station.value,
                }),
              ),
            )
        : [],
  });

  // Build PDF pages for current station
  const currentStationPages = useMemo(() => {
    if (!selectedDeliveryStation || tableData.length === 0) return null;
    const station = deliveryStations.find(
      (s) => s.value === selectedDeliveryStation,
    );
    return [
      {
        stationName: station?.label || "",
        members: tableData as unknown as (ShareDeliveryDetailsRow &
          Record<string, unknown>)[],
      },
    ];
  }, [selectedDeliveryStation, tableData, deliveryStations]);

  // Build PDF pages for all stations on selected day
  const allStationsDayPages = useMemo(() => {
    if (
      allStationsDayQueries.some((q) => q.isLoading) ||
      deliveryStations.length === 0
    )
      return null;
    const pages = deliveryStations
      .map((station, idx) => ({
        stationName: station.label,
        members: (allStationsDayQueries[idx]?.data ??
          []) as unknown as (ShareDeliveryDetailsRow &
          Record<string, unknown>)[],
      }))
      .filter((p) => p.members.length > 0);
    return pages.length > 0 ? pages : null;
  }, [allStationsDayQueries, deliveryStations]);

  // Build PDF pages for all stations across all days in the week
  const allStationsWeekPages = useMemo(() => {
    if (
      allStationsWeekQueries.some((q) => q.isLoading) ||
      deliveryStations.length === 0 ||
      dayNumbers.length === 0
    )
      return null;
    const validDays = dayNumbers.filter((d) => d !== null);
    const pages: {
      stationName: string;
      members: (ShareDeliveryDetailsRow & Record<string, unknown>)[];
    }[] = [];
    let queryIdx = 0;
    for (const dayNum of validDays) {
      const dayLabel = getDayName(dayNum, t);
      for (const station of deliveryStations) {
        const members = (allStationsWeekQueries[queryIdx]?.data ??
          []) as unknown as (ShareDeliveryDetailsRow &
          Record<string, unknown>)[];
        if (members.length > 0) {
          pages.push({
            stationName: `${station.label} — ${dayLabel}`,
            members,
          });
        }
        queryIdx++;
      }
    }
    return pages.length > 0 ? pages : null;
  }, [allStationsWeekQueries, deliveryStations, dayNumbers, t]);

  // Tenant info for PDF header
  const tenantInfo = useMemo(
    () => ({
      name: tenantName,
      logoUrl,
      email: (tenant?.email as string) || "",
      phone: (tenant?.phone_number as string) || "",
    }),
    [tenantName, logoUrl, tenant],
  );

  // Variation metadata for PDFs
  const pdfVariations = useMemo(
    () =>
      shareTypeVariations
        .filter((v) => v.id)
        .map((v) => ({
          id: v.id!,
          size: v.size,
          share_type: v.share_type,
          share_type_name: v.share_type_name ?? "",
        })),
    [shareTypeVariations],
  );

  const columns = useMemo<ColumnsType<any>>(() => {
    const baseColumns: ColumnsType<any> = [
      {
        title: t("commissioning.pickup_name"),
        dataIndex: "name",
        key: "name",
        align: "left",
        width: "15em",
        fixed: "left",
        render: (text: string) => <strong>{text || "-"}</strong>,
      },
    ];

    return [
      ...baseColumns,
      // EditableColumnConfig is a superset of Ant's column type — cast for
      // the Ant `Table` typing.
      ...(variationColumns as unknown as ColumnsType<unknown>),
    ];
  }, [variationColumns, t]);

  // NOTE: no "reset station to null on day/week change" effect here. That
  // unconditionally wiped a still-valid station (and blanked the table,
  // because the query is gated on a station being selected). The station
  // selector now reconciles itself via preserveSelection — it keeps the pick
  // when it's still scheduled for the new day, and only falls back to the
  // first station when it's gone.

  return (
    <div>
      <h1>
        {t("commissioning.delivery_notes_delivery_stations_details_title")}
      </h1>
      <div>
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
      </div>
      <div style={{ marginTop: "1em", marginLeft: "-2em" }}>
        <DeliveryStationSelector
          selectedDeliveryStation={selectedDeliveryStation}
          setSelectedDeliveryStation={setSelectedDeliveryStation}
          delivery_day={selectedDeliveryDayId}
          preserveSelection
        />
      </div>

      <div
        style={{
          display: "flex",
          flexDirection: "row",
          gap: "1em",
          marginTop: "1em",
        }}
      >
        <DeliveryStationDetailsPDFGenerator
          pages={currentStationPages}
          week={selectedWeek!}
          dayName={
            selectedDeliveryDay !== null
              ? getDayName(selectedDeliveryDay, t)
              : ""
          }
          variations={pdfVariations}
          tenant={tenantInfo}
          filename={generatePdfFilename([
            t("commissioning.pickup_list"),
            selectedYear,
            formatWeekLabel(selectedWeek, t),
            formatDayLabel(selectedDeliveryDay, t),
            (
              deliveryStations.find((s) => s.value === selectedDeliveryStation)
                ?.label ?? ""
            ).replace(/[^a-zA-Z0-9]/g, "_"),
          ])}
          buttonText={t("download.delivery_details_station")}
          t={t}
        />
        <ToolTipIcon
          title={t("tooltip.pickup_list_single_delivery_station")}
          style={{ marginLeft: "-1em" }}
        />

        <DeliveryStationDetailsPDFGenerator
          pages={allStationsDayPages}
          week={selectedWeek!}
          dayName={
            selectedDeliveryDay !== null
              ? getDayName(selectedDeliveryDay, t)
              : ""
          }
          variations={pdfVariations}
          tenant={tenantInfo}
          filename={generatePdfFilename([
            t("commissioning.pickup_lists"),
            selectedYear,
            formatWeekLabel(selectedWeek, t),
            formatDayLabel(selectedDeliveryDay, t),
            t("commissioning.all_day"),
          ])}
          buttonText={t("download.all_pdf_for_this_day")}
          t={t}
        />
        <ToolTipIcon
          title={t("tooltip.pickup_list_whole_day")}
          style={{ marginLeft: "-1em" }}
        />

        <DeliveryStationDetailsPDFGenerator
          pages={allStationsWeekPages}
          week={selectedWeek!}
          dayName={t("commissioning.whole_week")}
          variations={pdfVariations}
          tenant={tenantInfo}
          filename={generatePdfFilename([
            t("commissioning.pickup_lists"),
            selectedYear,
            formatWeekLabel(selectedWeek, t),
            t("commissioning.whole_week"),
          ])}
          buttonText={t("download.all_pdf_for_this_week")}
          t={t}
        />
        <ToolTipIcon
          title={t("tooltip.pickup_list_whole_week")}
          style={{ marginLeft: "-1em" }}
        />
      </div>

      <Table
        columns={columns}
        dataSource={tableData}
        pagination={false}
        size="small"
        loading={loading}
        className="custom-jasmin-table w-max"
        rowKey={(record) => record.id || record.name}
        bordered
        style={{ width: "max-content", marginTop: "2em" }}
        locale={{
          emptyText: (
            <div style={{ height: "4em" }}>
              {selectedDeliveryStation
                ? t("table.no_data")
                : t("commissioning.select_delivery_station")}
            </div>
          ),
        }}
      />

      <ExplainerText title={t("common.info")}>
        {t("explainers.delivery_stations_details")}
      </ExplainerText>
    </div>
  );
}
