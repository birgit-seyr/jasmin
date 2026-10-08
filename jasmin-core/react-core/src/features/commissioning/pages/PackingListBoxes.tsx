import { Alert, Button } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  useCommissioningPackingListBoxesMatrixRetrieve,
  useCommissioningPackingListMemberAmountsRetrieve,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningPackingListBoxesMatrixRetrieveParams,
  CommissioningPackingListMemberAmountsRetrieveParams,
  CommissioningSharesDeliveryDaysListParams,
  PackingBoxesMatrixColumn,
  PackingBoxesMatrixRow,
} from "@shared/api/generated/models";
import { DaySelector, WeekSelector } from "@shared/selectors";
import {
  DeliveryStationSelector,
  TourSelector,
} from "@features/commissioning/selectors";
import { ExplainerText } from "@shared/ui";
import { MobileStack } from "@shared/ui";
import {
  EditableTable,
  READ_ONLY_PERMISSION,
  SUMMARY_ROW_STYLE,
  wrapApiFunctions,
} from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  SummaryRow,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { PastWarningMessage } from "@shared/ui";
import {
  useBoxCombinationColumns,
  useDeliveryStationOfDay,
  usePackingBaseColumns,
  useShareContentGranularity,
  useShareDeliveryDays,
} from "@features/commissioning/hooks";
import type { ShareDeliveryDayOption } from "@features/commissioning/hooks/useShareDeliveryDays";
import {
  PackingListBoxesCountCard,
  PackingListBoxesMobileCard,
} from "@features/commissioning/components/mobileCards";
import { PackingBoxesMatrixPDFGenerator } from "@features/commissioning/pdfs";
import {
  useIsMobile,
  useNumberFormat,
  useTenant,
  useYearWeekState,
} from "@hooks/index";
import {
  activeAtDateForWeek,
  amountCellText,
  formatDayLabel,
  formatWeekLabel,
  generatePdfFilename,
  getDayName,
  isWeekInPast,
} from "@shared/utils";

/** The matrix the page shows: the boxes of each combination, or — for a farm
 *  that uploads its weekly share amounts — the amounts per share. */
function usePackingMatrix(
  params: CommissioningPackingListBoxesMatrixRetrieveParams,
  { enabled, usesExternalDemand }: { enabled: boolean; usesExternalDemand: boolean },
) {
  const boxesQuery = useCommissioningPackingListBoxesMatrixRetrieve(params, {
    query: { enabled: enabled && !usesExternalDemand },
  });
  const memberQuery = useCommissioningPackingListMemberAmountsRetrieve(
    params as CommissioningPackingListMemberAmountsRetrieveParams,
    { query: { enabled: enabled && usesExternalDemand } },
  );
  const query = usesExternalDemand ? memberQuery : boxesQuery;
  return {
    data: query.data,
    isFetching: query.isFetching,
    isError: query.isError,
    refetch: query.refetch,
  };
}

/**
 * Which part of the delivery day the list covers. The tenant's ShareContent
 * granularity decides it — not scoped to a share type, since the matrix spans
 * every share type: the whole day when every station gets the same amounts
 * (days_ok); one of the day's tours when the amounts are tour- but not
 * day-consistent and the day has several tours; and otherwise one of the
 * day's stations, which is also asked for while the granularity is loading.
 */
function usePackingScope({
  year,
  week,
  dayNumber,
  dayRecord,
}: {
  year: number;
  week: number | null;
  dayNumber: number | null;
  dayRecord: ShareDeliveryDayOption | undefined;
}) {
  const [selectedTour, setSelectedTour] = useState<number | "all">("all");
  const { daysOk, toursOk } = useShareContentGranularity({
    year,
    delivery_week: week ?? undefined,
    day_number: dayNumber ?? undefined,
  });

  const numberOfTours = dayRecord?.number_of_tours || 1;
  const tourSelectorActive = !daysOk && Boolean(toursOk) && numberOfTours > 1;
  const needsStation = !daysOk && !toursOk;

  // The tour picker offers only the day's tours, so the list asks for one of
  // them from the start: the first until another is picked, and the first
  // again when the picked one isn't among the day's.
  const effectiveTour = useMemo<number | undefined>(() => {
    if (!tourSelectorActive) return undefined;
    return selectedTour !== "all" && selectedTour <= numberOfTours
      ? selectedTour
      : 1;
  }, [tourSelectorActive, selectedTour, numberOfTours]);

  // The station is checked only while one is asked for, so a farm whose
  // stations all get the same amounts loads no station list.
  const [selectedDeliveryStation, setSelectedDeliveryStation, isStationOfDay] =
    useDeliveryStationOfDay(needsStation ? (dayRecord?.id ?? null) : null, {
      selectFirst: false,
    });

  return {
    tourSelectorActive,
    needsStation,
    selectedTour,
    setSelectedTour,
    effectiveTour,
    selectedDeliveryStation,
    setSelectedDeliveryStation,
    isStationOfDay,
  };
}

/**
 * Packing boxes MATRIX.
 *
 * Columns are the distinct box COMBINATIONS that actually occur — a base box
 * (non-additional share) plus the add-ons ("Zusatz") packed into it — derived
 * server-side from the week's subscriptions. Each combination header shows the
 * base size with a superscript badge per add-on (short_name·size). Rows are
 * share_articles; each cell is the per-box quantity of that article in that
 * combination. The pinned first row is the box count per combination.
 *
 * Scope: the tenant's ShareContent granularity decides which scope selector
 * is needed — nothing when every day has the same amounts (days_ok), a tour
 * selector when amounts are tour- but not day-consistent, and a required
 * delivery-station selector otherwise. The count row follows whichever scope
 * is active.
 */
export default function PackingListBoxes() {
  const { t } = useTranslation();
  const { getSetting } = useTenant();
  const isMobile = useIsMobile();

  // Shared identity columns (article / unit / size + note).
  const { baseColumns, noteColumn, withUnitSizeLabels } =
    usePackingBaseColumns();

  const showSize = Boolean(getSetting("show_size_column"));
  const packingMode = getSetting("packing_mode", "BOXES") as
    | "BOXES"
    | "BULK"
    | "MIXED";
  // Import-shares tenants have no ShareDelivery rows, so the box-combination
  // matrix is empty. Fall back to the flat per-variation matrix (member amounts,
  // ShareContent-based) — same {columns, rows} shape, just add_ons-empty columns.
  const usesExternalDemand = getSetting(
    "uploads_weekly_share_amount",
    false,
  ) as boolean;

  // --- Filters (scope). No ShareType selector — all share types at once. ---
  const {
    selectedYear,
    setSelectedYear,
    selectedWeek,
    setSelectedWeek,
    currentWeek,
  } = useYearWeekState();
  const [selectedDeliveryDay, setSelectedDeliveryDay] = useState<number | null>(
    () => dayjs().isoWeekday() - 1,
  );

  const isPast = useMemo(
    () => isWeekInPast(selectedYear, selectedWeek),
    [selectedYear, selectedWeek],
  );

  const shareDeliveryDaysParams =
    useMemo<CommissioningSharesDeliveryDaysListParams>(
      () => ({
        active_at_date: activeAtDateForWeek(selectedYear, selectedWeek),
      }),
      [selectedYear, selectedWeek],
    );
  const { shareDeliveryDays } = useShareDeliveryDays(shareDeliveryDaysParams);

  const deliveryDayOptions = useMemo<number[]>(
    () =>
      Array.from(
        new Set(shareDeliveryDays.map((day) => Number(day.day_number))),
      ).sort((a, b) => a - b),
    [shareDeliveryDays],
  );

  // Keep the pick on a real delivery day, snapping to the first available.
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

  const selectedDayRecord = useMemo<ShareDeliveryDayOption | undefined>(
    () =>
      selectedDeliveryDay === null
        ? undefined
        : shareDeliveryDays.find(
            (day) => Number(day.day_number) === Number(selectedDeliveryDay),
          ),
    [selectedDeliveryDay, shareDeliveryDays],
  );

  const getDeliveryDayId = selectedDayRecord?.id ?? null;

  const {
    tourSelectorActive,
    needsStation,
    selectedTour,
    setSelectedTour,
    effectiveTour,
    selectedDeliveryStation,
    setSelectedDeliveryStation,
    isStationOfDay,
  } = usePackingScope({
    year: selectedYear,
    week: selectedWeek,
    dayNumber: selectedDeliveryDay,
    dayRecord: selectedDayRecord,
  });

  const queryEnabled =
    selectedDeliveryDay !== null && (!needsStation || isStationOfDay);

  const matrixParams =
    useMemo<CommissioningPackingListBoxesMatrixRetrieveParams>(
      () => ({
        year: selectedYear,
        delivery_week: selectedWeek ?? currentWeek,
        day_number: selectedDeliveryDay ?? 0,
        delivery_station: needsStation
          ? (selectedDeliveryStation ?? undefined)
          : undefined,
        tour: effectiveTour,
        is_past: isPast,
        // In MIXED mode the boxes matrix excludes bulk-packed variations.
        ...(packingMode === "MIXED" ? { is_packed_bulk: false } : {}),
      }),
      [
        selectedYear,
        selectedWeek,
        currentWeek,
        selectedDeliveryDay,
        needsStation,
        selectedDeliveryStation,
        effectiveTour,
        isPast,
        packingMode,
      ],
    );

  const { data, isFetching, isError, refetch } = usePackingMatrix(matrixParams, {
    enabled: queryEnabled,
    usesExternalDemand,
  });

  const matrixColumns = useMemo<PackingBoxesMatrixColumn[]>(
    () => data?.columns ?? [],
    [data],
  );

  const rows = useMemo<TableRecord[]>(
    () =>
      withUnitSizeLabels(
        (data?.rows ?? []).map(
          (row: PackingBoxesMatrixRow) =>
            ({ ...row, key: row.id }) as TableRecord,
        ),
      ),
    [data, withUnitSizeLabels],
  );

  // A cell is an article's amount in one box of a combination, often a
  // fraction: shown at its unit's precision in the tenant's number format, on
  // screen, on the phone and on paper alike.
  const { format } = useNumberFormat();
  const amountText = useCallback(
    (value: unknown, record: Record<string, unknown>) =>
      amountCellText(value, record.unit as string | undefined, format),
    [format],
  );

  // --- Combination columns (grouped by base share_type) — the SAME columns
  // the delivery-station member matrix uses. ---
  const comboColumns = useBoxCombinationColumns(matrixColumns, {
    renderCell: amountText,
  });

  const columns = useMemo<EditableColumnConfig<TableRecord>[]>(
    () => [...baseColumns, ...comboColumns, noteColumn],
    [baseColumns, comboColumns, noteColumn],
  );

  // --- Pinned count row (boxes per combination in the current scope) ---
  // The flat per-variation (import) matrix carries per-share amounts, not box
  // counts, so it has no count row.
  const summaryRows = useMemo<SummaryRow[]>(
    () =>
      usesExternalDemand
        ? []
        : [
            {
              label: t("commissioning.box_count"),
              columns: matrixColumns.map((col) => col.key),
              // Strings so the summary renders "12", not the "12.00" path.
              data: Object.fromEntries(
                matrixColumns.map((col) => [col.key, String(col.count)]),
              ),
              style: SUMMARY_ROW_STYLE,
            },
          ],
    [matrixColumns, t, usesExternalDemand],
  );

  const apiFunctions = useMemo<ApiFunctions>(() => wrapApiFunctions({}), []);

  const dayName =
    selectedDeliveryDay !== null ? getDayName(selectedDeliveryDay, t) : "";
  const pdfFilename = generatePdfFilename([
    t("commissioning.packing_list_boxes"),
    selectedYear,
    formatWeekLabel(selectedWeek, t),
    formatDayLabel(selectedDeliveryDay, t),
  ]);

  // The matrix ran but produced no combination columns (no share type
  // variations for this scope) → show the warning instead of an empty grid.
  // A failed load is shown as such, never as a day without deliveries.
  const loadFailed = queryEnabled && !isFetching && isError;
  const noColumns =
    queryEnabled && !isFetching && !isError && matrixColumns.length === 0;

  return (
    <div>
      <h1>{t("commissioning.packing_list_boxes")}</h1>

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
        />
        {tourSelectorActive && (
          <TourSelector
            selectedTour={selectedTour}
            setSelectedTour={setSelectedTour}
            delivery_day={getDeliveryDayId}
            selectedYear={selectedYear}
            selectedWeek={selectedWeek}
          />
        )}
        {needsStation && (
          <DeliveryStationSelector
            selectedDeliveryStation={selectedDeliveryStation}
            setSelectedDeliveryStation={setSelectedDeliveryStation}
            delivery_day={getDeliveryDayId}
          />
        )}
      </MobileStack>

      {!isMobile && (
        <div
          className="section-divider"
          style={{ display: "flex", gap: "1em" }}
        >
          <PackingBoxesMatrixPDFGenerator
            columns={matrixColumns.length ? matrixColumns : null}
            data={rows.length ? rows : null}
            week={selectedWeek}
            dayName={dayName}
            showSize={showSize}
            // Flat per-variation (import) matrix has no box counts.
            showCountRow={!usesExternalDemand}
            cellText={amountText}
            filename={pdfFilename}
            buttonText={t("download.packing_list")}
            t={t}
          />
        </div>
      )}

      {isMobile && !usesExternalDemand && matrixColumns.length > 0 && (
        <PackingListBoxesCountCard groups={comboColumns} columns={matrixColumns} />
      )}

      {loadFailed && (
        <Alert
          type="error"
          showIcon
          message={t("table.load_failed_title")}
          description={t("table.load_failed_hint")}
          action={
            <Button size="small" onClick={() => refetch()}>
              {t("table.retry")}
            </Button>
          }
          className="editable-table-banner"
        />
      )}

      {noColumns ? (
        <PastWarningMessage>
          {t("commissioning.packing_list_no_columns")}
        </PastWarningMessage>
      ) : (
        <EditableTable
          key={`${selectedYear}-${selectedWeek}-${selectedDeliveryDay}-${selectedDeliveryStation}-${effectiveTour}`}
          columns={columns as EditableColumnConfig[]}
          apiFunctions={apiFunctions}
          initialData={rows}
          loading={isFetching}
          permissions={READ_ONLY_PERMISSION}
          summaryRows={summaryRows}
          summaryPosition="bottom"
          summaryLabelColumnIndex={0}
          className="w-max custom-jasmin-table"
          renderMobileCard={(record) => (
            <PackingListBoxesMobileCard
              record={record}
              groups={comboColumns}
              columns={matrixColumns}
              amountText={amountText}
            />
          )}
        />
      )}
      {!isMobile && (
        <ExplainerText title={t("common.info")}>
          {t("explainers.packing_list_boxes")}
        </ExplainerText>
      )}
    </div>
  );
}
