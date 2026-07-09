import dayjs from "dayjs";
import { useEffect, useMemo, useState } from "react";
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
  usePackingBaseColumns,
  useShareContentGranularity,
  useShareDeliveryDays,
} from "@features/commissioning/hooks";
import type { ShareDeliveryDayOption } from "@features/commissioning/hooks/useShareDeliveryDays";
import { PackingBoxesMatrixPDFGenerator } from "@features/commissioning/pdfs";
import {
  currentWeek,
  useIsMobile,
  useTenant,
  useYearWeekState,
} from "@hooks/index";
import {
  activeAtDateForWeek,
  formatDayLabel,
  formatWeekLabel,
  generatePdfFilename,
  getDayName,
  isWeekInPast,
} from "@shared/utils";

const currentDay = dayjs().isoWeekday();

/**
 * Packing boxes MATRIX (v2 of PackingListBoxes).
 *
 * Columns are the distinct box COMBINATIONS that actually occur — a base box
 * (non-additional share) plus the add-ons ("Zusatz") packed into it — derived
 * server-side from the week's subscriptions. Each combination header shows the
 * base size with a superscript badge per add-on (short_name·size). Rows are
 * share_articles; each cell is the per-box quantity of that article in that
 * combination. The pinned first row is the box count per combination.
 *
 * Scope + granularity mirror PackingListBoxes: the tenant's ShareContent
 * granularity decides which scope selector is needed — nothing when every day
 * has the same amounts (days_ok), a tour selector when amounts are tour- but
 * not day-consistent, and a required delivery-station selector otherwise. The
 * count row follows whichever scope is active.
 */
export default function PackingListBoxes() {
  const { t } = useTranslation();
  const { getSetting } = useTenant();
  const isMobile = useIsMobile();

  // Shared identity columns (article / unit / size + note) — the SAME left
  // columns PackingListBoxes uses.
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
  const { selectedYear, setSelectedYear, selectedWeek, setSelectedWeek } =
    useYearWeekState();
  const [selectedDeliveryDay, setSelectedDeliveryDay] = useState<number | null>(
    currentDay - 1,
  );
  const [selectedDeliveryStation, setSelectedDeliveryStation] = useState<
    string | null
  >(null);
  const [selectedTour, setSelectedTour] = useState<number | "all">("all");

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

  const hasMultipleToursForSelectedDay = useMemo(() => {
    if (!selectedDayRecord) return false;
    const tours =
      ((selectedDayRecord as unknown as Record<string, unknown>)
        .number_of_tours as number) || 1;
    return tours > 1;
  }, [selectedDayRecord]);

  // --- Granularity (inherited from PackingListBoxes) ---
  // Not scoped to a share_type: the matrix spans every share type, so it needs
  // the strictest (per-day, all-share-types) granularity.
  const { daysOk, toursOk } = useShareContentGranularity({
    year: selectedYear,
    delivery_week: selectedWeek ?? undefined,
    day_number: selectedDeliveryDay ?? undefined,
  });

  // Tour selector is live only when amounts are tour- but not day-consistent
  // AND the day actually has multiple tours. Station selector (and a required
  // station) appears when amounts are neither day- nor tour-consistent. While
  // granularity is still loading (null) we conservatively require a station,
  // exactly like PackingListBoxes.
  const tourSelectorActive =
    !daysOk && Boolean(toursOk) && hasMultipleToursForSelectedDay;
  const needsStation = !daysOk && !toursOk;

  const effectiveTour = useMemo<number | undefined>(() => {
    if (!tourSelectorActive || selectedTour === "all") return undefined;
    return selectedTour;
  }, [tourSelectorActive, selectedTour]);

  const queryEnabled =
    selectedDeliveryDay !== null &&
    (!needsStation || selectedDeliveryStation !== null);

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
        selectedDeliveryDay,
        needsStation,
        selectedDeliveryStation,
        effectiveTour,
        isPast,
        packingMode,
      ],
    );

  const boxesQuery = useCommissioningPackingListBoxesMatrixRetrieve(matrixParams, {
    query: { enabled: queryEnabled && !usesExternalDemand },
  });
  const memberQuery = useCommissioningPackingListMemberAmountsRetrieve(
    matrixParams as CommissioningPackingListMemberAmountsRetrieveParams,
    { query: { enabled: queryEnabled && usesExternalDemand } },
  );
  const data = usesExternalDemand ? memberQuery.data : boxesQuery.data;
  const isFetching = usesExternalDemand
    ? memberQuery.isFetching
    : boxesQuery.isFetching;

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

  // --- Combination columns (grouped by base share_type) — the SAME columns
  // the delivery-station member matrix uses. ---
  const comboColumns = useBoxCombinationColumns(matrixColumns);

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
  const noColumns = queryEnabled && !isFetching && matrixColumns.length === 0;

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
            filename={pdfFilename}
            buttonText={t("download.packing_list")}
            t={t}
          />
        </div>
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
