import { useQueries } from "@tanstack/react-query";
import { Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  getCommissioningPackingListMemberAmountsRetrieveQueryOptions,
  getCommissioningShareDeliveryDetailsMatrixRetrieveQueryOptions,
  useCommissioningPackingListMemberAmountsRetrieve,
  useCommissioningShareDeliveryDetailsMatrixRetrieve,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningPackingListMemberAmountsRetrieveParams,
  CommissioningShareDeliveryDetailsMatrixRetrieveParams,
  PackingBoxesMatrix,
  PackingBoxesMatrixColumn,
  StationMemberMatrix,
} from "@shared/api/generated/models";
import { ImportSharesModeBanner } from "@features/commissioning/components";
import { DeliveryStationDetailsPDFGenerator } from "@features/commissioning/pdfs";
import type { StationPageData } from "@features/commissioning/pdfs/exports/DeliveryStationDetailsPDF";
import { DaySelector, WeekSelector } from "@shared/selectors";
import { DeliveryStationSelector } from "@features/commissioning/selectors";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import { ExplainerText, PastWarningMessage, ToolTipIcon } from "@shared/ui";
import { useSizeOptions, useTenant, useUnitOptions } from "@hooks/index";
import {
  useBoxCombinationColumns,
  useDeliveryStations,
  useShareDeliveryDays,
} from "@features/commissioning/hooks";
import {
  activeAtDateForWeek,
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
  const { tenantName, logoUrl, tenant, getSetting } = useTenant();
  const { getUnitLabel } = useUnitOptions();
  const { getSizeLabel } = useSizeOptions();
  const usesExternalDemand = getSetting(
    "uploads_weekly_share_amount",
    false,
  ) as boolean;
  const showSize = Boolean(getSetting("show_size_column"));

  // Turn a per-station member-amounts matrix into the ``StationPageData``
  // member-matrix fields: the "Was ihr nehmen könnt" columns + rows (with
  // unit/size resolved to labels for the PDF). Attached to each station's page
  // so it prints right after that station's pickup list.
  const buildMemberMatrix = useCallback(
    (m: PackingBoxesMatrix | undefined) => ({
      memberColumns: m?.columns ?? [],
      memberRows: (m?.rows ?? []).map((row) => ({
        ...row,
        unit_label: row.unit ? getUnitLabel(row.unit) : "",
        size_label: row.size ? getSizeLabel(row.size) : "",
      })),
      showSize,
    }),
    [getUnitLabel, getSizeLabel, showSize],
  );

  // delivery days — derived purely from the selected year/week (no effect).
  const shareDeliveryDaysFilters = useMemo(
    () => ({
      active_at_date: activeAtDateForWeek(selectedYear, selectedWeek),
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

  // --- Combination matrix (members × box combinations) for the table AND
  // the pickup-list PDFs — both render the same box-combination columns. ---
  const matrixParams =
    useMemo<CommissioningShareDeliveryDetailsMatrixRetrieveParams>(
      () => ({
        year: selectedYear,
        delivery_week: selectedWeek ?? 0,
        day_number: selectedDeliveryDay ?? 0,
        delivery_station: selectedDeliveryStation ?? "",
      }),
      [selectedYear, selectedWeek, selectedDeliveryDay, selectedDeliveryStation],
    );
  const { data: matrix, isFetching: matrixFetching } =
    useCommissioningShareDeliveryDetailsMatrixRetrieve(matrixParams, {
      query: { enabled: isQueryEnabled },
    });
  const matrixColumns = useMemo<PackingBoxesMatrixColumn[]>(
    () => (isQueryEnabled ? (matrix?.columns ?? []) : []),
    [isQueryEnabled, matrix],
  );
  const matrixRows = useMemo<TableRecord[]>(
    () =>
      isQueryEnabled ? ((matrix?.rows ?? []) as unknown as TableRecord[]) : [],
    [isQueryEnabled, matrix],
  );
  const comboColumns = useBoxCombinationColumns(matrixColumns);
  const loading = isQueryEnabled && matrixFetching;

  // "Was ihr nehmen könnt" (member per-share amounts, is_packed_bulk portion —
  // same as PackingListBulk) for the CURRENT station. Appended after the
  // station's pickup page in the PDF.
  const currentMemberParams =
    useMemo<CommissioningPackingListMemberAmountsRetrieveParams>(
      () => ({
        year: selectedYear,
        delivery_week: selectedWeek ?? 0,
        day_number: selectedDeliveryDay ?? 0,
        delivery_station: selectedDeliveryStation ?? "",
        is_packed_bulk: true,
      }),
      [selectedYear, selectedWeek, selectedDeliveryDay, selectedDeliveryStation],
    );
  const { data: currentMemberMatrix } =
    useCommissioningPackingListMemberAmountsRetrieve(currentMemberParams, {
      query: { enabled: isQueryEnabled },
    });

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

  // Bulk fetch: the combination matrix for every station on the selected day
  // (fired once the current view has data). Each result carries that station's
  // own columns + member rows.
  const allStationsDayQueries = useQueries({
    queries:
      matrixRows.length > 0 &&
      selectedDeliveryDay !== null &&
      deliveryStations.length > 0
        ? deliveryStations.map((station) =>
            getCommissioningShareDeliveryDetailsMatrixRetrieveQueryOptions({
              year: selectedYear,
              delivery_week: selectedWeek!,
              day_number: selectedDeliveryDay,
              delivery_station: station.value,
            }),
          )
        : [],
  });

  // Parallel member-amounts ("Was ihr nehmen könnt") per station on the day —
  // mirrors allStationsDayQueries so each pickup page can carry its member page.
  const allStationsDayMemberQueries = useQueries({
    queries:
      matrixRows.length > 0 &&
      selectedDeliveryDay !== null &&
      deliveryStations.length > 0
        ? deliveryStations.map((station) =>
            getCommissioningPackingListMemberAmountsRetrieveQueryOptions({
              year: selectedYear,
              delivery_week: selectedWeek!,
              day_number: selectedDeliveryDay,
              delivery_station: station.value,
              is_packed_bulk: true,
            }),
          )
        : [],
  });

  // Bulk fetch: the combination matrix for every station across every day of
  // the week.
  const allStationsWeekQueries = useQueries({
    queries:
      matrixRows.length > 0 &&
      dayNumbers.length > 0 &&
      deliveryStations.length > 0
        ? dayNumbers
            .filter((d) => d !== null)
            .flatMap((dayNum) =>
              deliveryStations.map((station) =>
                getCommissioningShareDeliveryDetailsMatrixRetrieveQueryOptions({
                  year: selectedYear,
                  delivery_week: selectedWeek!,
                  day_number: dayNum,
                  delivery_station: station.value,
                }),
              ),
            )
        : [],
  });

  // Parallel member-amounts per station × day — mirrors allStationsWeekQueries.
  const allStationsWeekMemberQueries = useQueries({
    queries:
      matrixRows.length > 0 &&
      dayNumbers.length > 0 &&
      deliveryStations.length > 0
        ? dayNumbers
            .filter((d) => d !== null)
            .flatMap((dayNum) =>
              deliveryStations.map((station) =>
                getCommissioningPackingListMemberAmountsRetrieveQueryOptions({
                  year: selectedYear,
                  delivery_week: selectedWeek!,
                  day_number: dayNum,
                  delivery_station: station.value,
                  is_packed_bulk: true,
                }),
              ),
            )
        : [],
  });

  // Build PDF pages for the current station — reuses the already-fetched matrix.
  const currentStationPages = useMemo<StationPageData[] | null>(() => {
    if (!selectedDeliveryStation || matrixRows.length === 0) return null;
    const station = deliveryStations.find(
      (s) => s.value === selectedDeliveryStation,
    );
    return [
      {
        stationName: station?.label || "",
        columns: matrixColumns,
        rows: matrixRows as unknown as StationPageData["rows"],
        ...buildMemberMatrix(currentMemberMatrix),
      },
    ];
  }, [
    selectedDeliveryStation,
    matrixColumns,
    matrixRows,
    deliveryStations,
    currentMemberMatrix,
    buildMemberMatrix,
  ]);

  // Build PDF pages for all stations on the selected day.
  const allStationsDayPages = useMemo<StationPageData[] | null>(() => {
    if (
      allStationsDayQueries.some((q) => q.isLoading) ||
      allStationsDayMemberQueries.some((q) => q.isLoading) ||
      deliveryStations.length === 0
    )
      return null;
    const pages = deliveryStations
      .map((station, idx): StationPageData => {
        const stationMatrix = allStationsDayQueries[idx]?.data as
          | StationMemberMatrix
          | undefined;
        return {
          stationName: station.label,
          columns: stationMatrix?.columns ?? [],
          rows: (stationMatrix?.rows ??
            []) as unknown as StationPageData["rows"],
          ...buildMemberMatrix(
            allStationsDayMemberQueries[idx]?.data as
              | PackingBoxesMatrix
              | undefined,
          ),
        };
      })
      .filter((page) => page.rows.length > 0);
    return pages.length > 0 ? pages : null;
  }, [
    allStationsDayQueries,
    allStationsDayMemberQueries,
    deliveryStations,
    buildMemberMatrix,
  ]);

  // Build PDF pages for all stations across all days in the week.
  const allStationsWeekPages = useMemo<StationPageData[] | null>(() => {
    if (
      allStationsWeekQueries.some((q) => q.isLoading) ||
      allStationsWeekMemberQueries.some((q) => q.isLoading) ||
      deliveryStations.length === 0 ||
      dayNumbers.length === 0
    )
      return null;
    const validDays = dayNumbers.filter((d) => d !== null);
    const pages: StationPageData[] = [];
    let queryIdx = 0;
    for (const dayNum of validDays) {
      const dayLabel = getDayName(dayNum, t);
      for (const station of deliveryStations) {
        const stationMatrix = allStationsWeekQueries[queryIdx]?.data as
          | StationMemberMatrix
          | undefined;
        const rows = (stationMatrix?.rows ??
          []) as unknown as StationPageData["rows"];
        if (rows.length > 0) {
          pages.push({
            stationName: `${station.label} — ${dayLabel}`,
            columns: stationMatrix?.columns ?? [],
            rows,
            ...buildMemberMatrix(
              allStationsWeekMemberQueries[queryIdx]?.data as
                | PackingBoxesMatrix
                | undefined,
            ),
          });
        }
        queryIdx++;
      }
    }
    return pages.length > 0 ? pages : null;
  }, [
    allStationsWeekQueries,
    allStationsWeekMemberQueries,
    deliveryStations,
    dayNumbers,
    t,
    buildMemberMatrix,
  ]);

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
      // The SAME combination columns the packing boxes matrix uses. Cast:
      // EditableColumnConfig is a superset of Ant's column type.
      ...(comboColumns as unknown as ColumnsType<unknown>),
    ];
  }, [comboColumns, t]);

  // NOTE: no "reset station to null on day/week change" effect here. That
  // unconditionally wiped a still-valid station (and blanked the table,
  // because the query is gated on a station being selected). The station
  // selector now reconciles itself via preserveSelection — it keeps the pick
  // when it's still scheduled for the new day, and only falls back to the
  // first station when it's gone.

  // Pickup lists are inherently per-member (rows are members); import-shares
  // tenants have no members / ShareDeliveries, so the list can't be built. Show
  // the "not available" notice instead of an empty grid + dead PDF buttons.
  if (usesExternalDemand) {
    return (
      <div>
        <h1>
          {t("commissioning.delivery_notes_delivery_stations_details_title")}
        </h1>
        <ImportSharesModeBanner messageKey="commissioning.pickup_lists_import_unavailable" />
      </div>
    );
  }

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

      {isQueryEnabled && !loading && matrixColumns.length === 0 ? (
        <PastWarningMessage>
          {t("commissioning.packing_list_no_columns")}
        </PastWarningMessage>
      ) : (
        <Table
          columns={columns}
          dataSource={matrixRows}
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
      )}

      <ExplainerText title={t("common.info")}>
        {t("explainers.delivery_stations_details")}
      </ExplainerText>
    </div>
  );
}
