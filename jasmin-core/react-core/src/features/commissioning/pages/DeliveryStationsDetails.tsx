import { useQueries } from "@tanstack/react-query";
import { Table } from "antd";
import type { ColumnsType } from "antd/es/table";
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
import {
  useVegetableSizeOptions,
  useTenant,
  useUnitOptions,
  useYearWeekState,
} from "@hooks/index";
import {
  useBoxCombinationColumns,
  useDeliveryStations,
  useDeliveryStationsPerDay,
  useShareDeliveryDays,
} from "@features/commissioning/hooks";
import {
  activeAtDateForWeek,
  formatDayLabel,
  formatWeekLabel,
  generatePdfFilename,
  getDayName,
} from "@shared/utils";

/**
 * The week's delivery days, each paired with the stations IT serves — every
 * day has its own, so the week's pages pair a day only with its stations.
 * Empty until every day's stations have loaded.
 */
function useWeekStationSlots(
  dayNumbers: number[],
  shareDeliveryDays: { id?: unknown; day_number?: unknown }[],
) {
  const weekDeliveryDays = useMemo(
    () =>
      dayNumbers.flatMap((dayNum) => {
        const id = shareDeliveryDays.find((day) => day.day_number === dayNum)?.id;
        return id ? [{ dayNum, id: String(id) }] : [];
      }),
    [dayNumbers, shareDeliveryDays],
  );
  const { stationsPerDay, loading } = useDeliveryStationsPerDay(
    weekDeliveryDays.map((day) => day.id),
  );
  return useMemo(
    () =>
      loading
        ? []
        : weekDeliveryDays.flatMap(({ dayNum }, index) =>
            (stationsPerDay[index] ?? []).map((station) => ({ dayNum, station })),
          ),
    [weekDeliveryDays, stationsPerDay, loading],
  );
}

type StationQuery = { data?: unknown; isLoading: boolean };

/**
 * One PDF page per named station that has pickups, the pickup matrix and the
 * take-home amounts read from the queries at the same index. Null while any
 * of them loads, or when no station has pickups.
 */
function buildStationPages(
  stationNames: string[],
  matrixQueries: StationQuery[],
  memberQueries: StationQuery[],
  buildMemberMatrix: (
    matrix: PackingBoxesMatrix | undefined,
  ) => Omit<StationPageData, "stationName" | "columns" | "rows">,
): StationPageData[] | null {
  if (
    stationNames.length === 0 ||
    matrixQueries.some((query) => query.isLoading) ||
    memberQueries.some((query) => query.isLoading)
  )
    return null;
  const pages = stationNames.flatMap((stationName, index) => {
    const matrix = matrixQueries[index]?.data as StationMemberMatrix | undefined;
    const rows = (matrix?.rows ?? []) as unknown as StationPageData["rows"];
    if (rows.length === 0) return [];
    const member = memberQueries[index]?.data as PackingBoxesMatrix | undefined;
    return [
      {
        stationName,
        columns: matrix?.columns ?? [],
        rows,
        ...buildMemberMatrix(member),
      },
    ];
  });
  return pages.length > 0 ? pages : null;
}

export default function DeliveryStationsDetails() {
  const { selectedYear, setSelectedYear, selectedWeek, setSelectedWeek } =
    useYearWeekState();
  const [selectedDeliveryDay, setSelectedDeliveryDay] = useState<number | null>(
    null,
  );
  const [selectedDeliveryStation, setSelectedDeliveryStation] = useState<
    string | null
  >(null);

  const { t } = useTranslation();
  const { tenantName, logoUrl, tenant, getSetting } = useTenant();
  const { getUnitLabel } = useUnitOptions();
  const { getVegetableSizeLabel } = useVegetableSizeOptions();
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
        size_label: row.size ? getVegetableSizeLabel(row.size) : "",
      })),
      showSize,
    }),
    [getUnitLabel, getVegetableSizeLabel, showSize],
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

  // Select the first delivery day when the selected day isn't one of them
  useEffect(() => {
    if (
      dayNumbers.length > 0 &&
      !dayNumbers.some((day) => day === selectedDeliveryDay)
    ) {
      setSelectedDeliveryDay(dayNumbers[0]);
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
  const {
    data: matrix,
    isFetching: matrixFetching,
    isError: matrixError,
  } = useCommissioningShareDeliveryDetailsMatrixRetrieve(matrixParams, {
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
  // A failed load is shown as such, never as a station nobody collects at.
  const matrixFailed = isQueryEnabled && !loading && matrixError;

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
    if (selectedDeliveryDay === null) {
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

  // Bulk fetch: the combination matrix for every station on the selected day,
  // fired once the day's stations are known — independent of the station on
  // screen, which may have nobody collecting. Each result carries that
  // station's own columns + member rows.
  const allStationsDayQueries = useQueries({
    queries:
      selectedDeliveryDay !== null && deliveryStations.length > 0
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
      selectedDeliveryDay !== null && deliveryStations.length > 0
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

  const weekSlots = useWeekStationSlots(dayNumbers, shareDeliveryDays);

  // Bulk fetch: the combination matrix for every station on every day of the
  // week it serves.
  const allStationsWeekQueries = useQueries({
    queries: weekSlots.map(({ dayNum, station }) =>
      getCommissioningShareDeliveryDetailsMatrixRetrieveQueryOptions({
        year: selectedYear,
        delivery_week: selectedWeek!,
        day_number: dayNum,
        delivery_station: station.value,
      }),
    ),
  });

  // Parallel member-amounts per station and day — mirrors allStationsWeekQueries.
  const allStationsWeekMemberQueries = useQueries({
    queries: weekSlots.map(({ dayNum, station }) =>
      getCommissioningPackingListMemberAmountsRetrieveQueryOptions({
        year: selectedYear,
        delivery_week: selectedWeek!,
        day_number: dayNum,
        delivery_station: station.value,
        is_packed_bulk: true,
      }),
    ),
  });

  // Build PDF pages for the current station — reuses the already-fetched
  // matrix. Waits for the take-home amounts too, so the sheet never prints
  // without them.
  const currentStationPages = useMemo<StationPageData[] | null>(() => {
    if (
      !selectedDeliveryStation ||
      matrixRows.length === 0 ||
      !currentMemberMatrix
    )
      return null;
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
  const allStationsDayPages = useMemo(
    () =>
      buildStationPages(
        deliveryStations.map((station) => station.label),
        allStationsDayQueries,
        allStationsDayMemberQueries,
        buildMemberMatrix,
      ),
    [
      allStationsDayQueries,
      allStationsDayMemberQueries,
      deliveryStations,
      buildMemberMatrix,
    ],
  );

  // Build PDF pages for all stations across all days in the week.
  const allStationsWeekPages = useMemo(
    () =>
      buildStationPages(
        weekSlots.map(
          ({ dayNum, station }) => `${station.label} — ${getDayName(dayNum, t)}`,
        ),
        allStationsWeekQueries,
        allStationsWeekMemberQueries,
        buildMemberMatrix,
      ),
    [
      allStationsWeekQueries,
      allStationsWeekMemberQueries,
      weekSlots,
      t,
      buildMemberMatrix,
    ],
  );

  const selectedDayName =
    selectedDeliveryDay !== null ? getDayName(selectedDeliveryDay, t) : "";

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

  // NOTE: no "reset station to null on day/week change" effect here — it
  // would wipe a still-valid station (and blank the table, because the query
  // is gated on a station being selected). The station selector reconciles
  // itself via preserveSelection — it keeps the pick when it's still
  // scheduled for the new day, and only falls back to the first station when
  // it's gone.

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
      <p className="page-subtitle">{t("commissioning.pickup_lists_subtitle")}</p>
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
          dayName={selectedDayName}
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
          dayName={selectedDayName}
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

      {isQueryEnabled &&
      !loading &&
      !matrixFailed &&
      matrixColumns.length === 0 ? (
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
          rowKey="id"
          bordered
          style={{ width: "max-content", marginTop: "2em" }}
          locale={{
            emptyText: (
              <div style={{ height: "4em" }}>
                {matrixFailed
                  ? t("common.error_loading_data")
                  : selectedDeliveryStation
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
