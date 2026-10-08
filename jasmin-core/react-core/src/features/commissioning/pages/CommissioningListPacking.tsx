import { Alert, Button } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  dayPlannedAmountKey,
  useAmountUnitSizeColumns,
  usePackingModeShareGroups,
  useShareArticleColumn,
  useShareDeliveryDays,
} from "@features/commissioning/hooks";
import { CommissioningListPackingPDFGenerator } from "@features/commissioning/pdfs";
import { SharesDeliveryDaySelector } from "@features/commissioning/selectors";
import {
  useIsMobile,
  useNumberFormat,
  useTenant,
  useUnitOptions,
  useVegetableSizeOptions,
  useYearWeekState,
} from "@hooks/index";
import { useCommissioningHarvestSharePlanningList } from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningHarvestSharePlanningListParams,
  HarvestSharePlanningRow,
  ShareTypeEnum,
} from "@shared/api/generated/models";
import { WeekSelector } from "@shared/selectors";
import { EditableTable, READ_ONLY_PERMISSION } from "@shared/tables";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { ExplainerText, MobileStack } from "@shared/ui";
import {
  activeAtDateForWeek,
  formatAmountForUnit,
  formatDayLabel,
  formatWeekLabel,
  generatePdfFilename,
  getDayName,
  getShareOptionLabel,
  isWeekInPast,
} from "@shared/utils";

const shareArticleFilters = {
  is_harvest_share_article: true,
  is_active: true,
};

interface PackingRow extends TableRecord {
  key: string;
  id: string;
  share_article: string;
  share_article_name: string;
  size: string | null;
  unit: string | null;
  total_amount: number;
}

/**
 * Pull the rows for one delivery day out of a ``harvest_share_planning``
 * response. Each row's ``day_<deliveryDayId>_planned_amount`` is already the
 * across-stations, no-buffer total (``Σ share_content.amount × variation
 * demand``) grouped by ``(share_article, size, unit)``; we just surface the
 * column for the selected day and drop rows with no demand that day.
 */
function buildRows(
  rawData: (HarvestSharePlanningRow & Record<string, unknown>)[] | undefined,
  deliveryDayId: string | null,
): PackingRow[] {
  if (!Array.isArray(rawData) || !deliveryDayId) return [];
  const plannedKey = dayPlannedAmountKey(deliveryDayId);
  const result: PackingRow[] = [];
  for (const row of rawData) {
    const rawAmount = row[plannedKey];
    const baseAmount = rawAmount != null ? parseFloat(String(rawAmount)) : 0;
    if (!baseAmount || baseAmount <= 0) continue;
    // Spoilage buffer: the picker grabs `pct`% extra so ~pct% bad items still
    // leave enough good ones. Rounded UP to a whole unit — it's an actionable
    // pick list ("grab N"), and the buffer's intent is "have at least enough".
    // The product is cut to a few decimals first: in binary floating point
    // 100 × 1.1 is 110.00000000000001, which would round up to 111.
    const pct =
      Number(row.percentage_added_to_commissioning_list_packing) || 0;
    const withBuffer = (baseAmount * (100 + pct)) / 100;
    const amount = Math.ceil(Number(withBuffer.toFixed(6)));
    const id = String(row.id);
    result.push({
      key: id,
      id,
      share_article: row.share_article,
      share_article_name: String(row.share_article_name ?? ""),
      size: (row.size as string | null) ?? null,
      unit: (row.unit as string | null) ?? null,
      total_amount: amount,
    });
  }
  return result;
}

interface ShareOptionPackingTableProps {
  shareOption: string;
  label: string;
  showHeading: boolean;
  columns: EditableColumnConfig<TableRecord>[];
  year: number;
  week: number | null;
  /** Today's week, read when the page mounted. */
  currentWeek: number;
  deliveryDayId: string | null;
  /** Reports this option's resolved rows up to the parent so they can be
   *  collected into the PDF (each table owns its own fetch) — `null` while
   *  they are loading or after their load failed. */
  onRowsChange?: (shareOption: string, rows: PackingRow[] | null) => void;
}

/**
 * The consolidated truck-prep table for a single share option (e.g. veg vs.
 * fruit). One of these is rendered per active share option, so the active
 * variations of each option get their own table rather than being folded
 * together.
 */
function ShareOptionPackingTable({
  shareOption,
  label,
  showHeading,
  columns,
  year,
  week,
  currentWeek,
  deliveryDayId,
  onRowsChange,
}: ShareOptionPackingTableProps) {
  const { t } = useTranslation();
  const listParams = useMemo<CommissioningHarvestSharePlanningListParams>(
    () => ({
      year,
      // Always a valid number for the type; the query is disabled below when
      // the week is actually cleared, so this fallback never hits the wire.
      delivery_week: week ?? currentWeek,
      // shareOption prop is a string; the list param is the generated enum.
      share_option: shareOption as ShareTypeEnum,
      // A week further back is read from the stored rows, as the planning
      // page reads it.
      is_past: isWeekInPast(year, week),
    }),
    [year, week, currentWeek, shareOption],
  );

  const { data: rawData, isFetching, isError, refetch } =
    useCommissioningHarvestSharePlanningList<
      (HarvestSharePlanningRow & Record<string, unknown>)[]
    >(listParams, { query: { enabled: week !== null } });
  // A failed refetch keeps the rows it already has; only a plan never loaded
  // is missing from the list.
  const loadFailed = isError && rawData === undefined;

  const rows = useMemo(
    () => buildRows(rawData, deliveryDayId),
    [rawData, deliveryDayId],
  );

  useEffect(() => {
    onRowsChange?.(shareOption, isFetching || loadFailed ? null : rows);
  }, [shareOption, rows, isFetching, loadFailed, onRowsChange]);

  return (
    <section className="commissioning-list-packing-section">
      {showHeading && (
        <h3 className="commissioning-list-packing-section__heading">{label}</h3>
      )}
      {loadFailed && !isFetching && (
        <Alert
          type="error"
          showIcon
          message={t("commissioning.share_option_load_failed", {
            option: label,
          })}
          description={t("table.load_failed_hint")}
          action={
            <Button size="small" onClick={() => refetch()}>
              {t("table.retry")}
            </Button>
          }
          className="editable-table-banner"
        />
      )}
      <EditableTable
        key={`${year}-${week}-${deliveryDayId}-${shareOption}`}
        columns={columns}
        initialData={rows}
        permissions={READ_ONLY_PERMISSION}
        loading={isFetching}
        className="w-max custom-jasmin-table"
      />
    </section>
  );
}

/**
 * Consolidated truck-prep packing list: everything to prepare for one delivery
 * day, treated as if it were all bulk-packed and summed across ALL delivery
 * stations — ``share_content.amount × variation demand`` grouped by
 * ``(share_article, size, unit)``.
 *
 * Reuses the ``harvest_share_planning`` endpoint (its
 * ``day_<deliveryDayId>_planned_amount`` is exactly that figure). When the
 * tenant runs separate fruit + vegetable shares, each active harvest share
 * option gets its own table.
 */
export default function CommissioningListPacking() {
  const { t } = useTranslation();
  // One table per ACTIVE share option — this list is the total of everything
  // needed for packing AND bulk, so it covers every option (bulk or boxed),
  // not just the bulk-packed ones.
  const {
    selectedYear,
    setSelectedYear,
    selectedWeek,
    setSelectedWeek,
    currentWeek,
  } = useYearWeekState();
  const [selectedDeliveryDayId, setSelectedDeliveryDayId] = useState<
    string | null
  >(null);

  // The share options and delivery days of the chosen week, not of today.
  const activeAtDate = activeAtDateForWeek(selectedYear, selectedWeek);
  const {
    bulkShareOptions,
    boxesShareOptions,
    loading: shareOptionsLoading,
  } = usePackingModeShareGroups(activeAtDate);

  // The same list the day selector reads, to name the chosen day.
  const { shareDeliveryDays } = useShareDeliveryDays({
    active_at_date: activeAtDate,
  });
  const selectedDayNumber = useMemo<number | null>(() => {
    const day = shareDeliveryDays.find(
      (deliveryDay) => deliveryDay.id === selectedDeliveryDayId,
    );
    return day ? Number(day.day_number) : null;
  }, [shareDeliveryDays, selectedDeliveryDayId]);
  const dayName =
    selectedDayNumber !== null ? getDayName(selectedDayNumber, t) : "";

  // Same column hooks the other harvest lists use, so the article / unit /
  // size cells render and align identically. Everything is read-only here
  // (``record.key`` is always a real id, never the -1 "new row" sentinel).
  const { shareArticleColumn } = useShareArticleColumn({
    filters: shareArticleFilters,
    showFruitsAndVegs: true,
    autofillContext: "harvest",
  });

  const { amountUnitSizeColumns } = useAmountUnitSizeColumns({
    overrides: {
      unit: { disabled: (record: TableRecord) => record.key !== -1 },
      size: { disabled: (record: TableRecord) => record.key !== -1 },
    },
    showAmount: false,
  });

  const { format } = useNumberFormat();

  const columns = useMemo<EditableColumnConfig<TableRecord>[]>(() => {
    const totalAmountColumn: EditableColumnConfig<TableRecord> = {
      title: t("commissioning.total_amount"),
      dataIndex: "total_amount",
      key: "total_amount",
      inputType: "positive_decimal2",
      align: "right",
      width: "10em",
      disabled: true,
      render: (value: unknown, record: TableRecord) => {
        const numeric = Number(value);
        if (!Number.isFinite(numeric)) return "";
        return formatAmountForUnit(numeric, record.unit as string | null, format);
      },
    };

    return [
      {
        ...shareArticleColumn,
        disabled: (record: TableRecord) => record.key !== -1,
      },
      ...amountUnitSizeColumns,
      totalAmountColumn,
    ];
  }, [t, shareArticleColumn, amountUnitSizeColumns, format]);

  // Every active share option (bulk or boxed), sorted for a stable render
  // order — the packing list totals what's needed across all of them.
  const shareOptionValues = useMemo(
    () =>
      Array.from(new Set([...bulkShareOptions, ...boxesShareOptions])).sort(),
    [bulkShareOptions, boxesShareOptions],
  );

  // Each table owns its own fetch, so collect their rows here to build the
  // PDF. ``handleRowsChange`` is stable and bails when a table reports the same
  // (memoised) rows reference, so it can't loop.
  const isMobile = useIsMobile();
  const { getUnitLabel } = useUnitOptions();
  const { getVegetableSizeLabel } = useVegetableSizeOptions();
  const { getSetting } = useTenant();
  // Mirror the on-screen size column (``useAmountUnitSizeColumns``): hidden
  // unless the tenant's ``show_size_column`` setting is truthy.
  const showSize = Boolean(getSetting("show_size_column"));
  const [rowsByOption, setRowsByOption] = useState<
    Record<string, PackingRow[] | null>
  >({});
  const handleRowsChange = useCallback((shareOption: string, rows: PackingRow[] | null) => {
    setRowsByOption((prev) =>
      prev[shareOption] === rows ? prev : { ...prev, [shareOption]: rows },
    );
  }, []);

  const pdfGroups = useMemo(
    () =>
      shareOptionValues
        .map((value) => ({
          label: getShareOptionLabel(value, t),
          rows: (rowsByOption[value] ?? []).map((row) => ({
            id: row.id,
            share_article_name: row.share_article_name,
            unit_label: row.unit ? getUnitLabel(row.unit) : "",
            size_label:
              row.size && row.size !== "M"
                ? getVegetableSizeLabel(row.size)
                : "",
            total_amount_text: formatAmountForUnit(
              row.total_amount,
              row.unit,
              format,
            ),
          })),
        }))
        .filter((group) => group.rows.length > 0),
    [
      shareOptionValues,
      rowsByOption,
      t,
      getUnitLabel,
      getVegetableSizeLabel,
      format,
    ],
  );

  // The PDF covers every share option, so it waits for all of their rows; a
  // table whose plan failed to load reports none and says so itself.
  const allRowsLoaded =
    !shareOptionsLoading &&
    shareOptionValues.every((value) => Array.isArray(rowsByOption[value]));

  const generateFilename = useMemo(
    () =>
      generatePdfFilename([
        t("commissioning.commissioning_list_packing"),
        selectedYear,
        formatWeekLabel(selectedWeek, t),
        formatDayLabel(selectedDayNumber, t),
      ]),
    [selectedYear, selectedWeek, selectedDayNumber, t],
  );

  return (
    <div>
      <h1>{t("commissioning.commissioning_list_packing")}</h1>
      <MobileStack>
        <WeekSelector
          selectedYear={selectedYear}
          setSelectedYear={setSelectedYear}
          selectedWeek={selectedWeek}
          setSelectedWeek={setSelectedWeek}
        />
        <SharesDeliveryDaySelector
          selectedSharesDeliveryDay={selectedDeliveryDayId}
          setSelectedSharesDeliveryDay={setSelectedDeliveryDayId}
          selectedYear={selectedYear}
          selectedWeek={selectedWeek}
          suffix={t("commissioning.delivery_day")}
        />
      </MobileStack>
      {!isMobile && (
        <div className="section-divider">
          <CommissioningListPackingPDFGenerator
            groups={pdfGroups}
            isReady={allRowsLoaded}
            year={selectedYear}
            week={selectedWeek}
            dayName={dayName}
            showSize={showSize}
            filename={generateFilename}
            buttonText={t("download.commissioning_list_packing")}
            t={t}
          />
        </div>
      )}
      {shareOptionValues.map((value) => (
        <ShareOptionPackingTable
          key={value}
          shareOption={value}
          label={getShareOptionLabel(value, t)}
          showHeading={shareOptionValues.length > 1}
          columns={columns}
          year={selectedYear}
          week={selectedWeek}
          currentWeek={currentWeek}
          deliveryDayId={selectedDeliveryDayId}
          onRowsChange={handleRowsChange}
        />
      ))}
      <ExplainerText title={t("common.info")}>
        {t("explainers.commissioning_lists_packing")}
      </ExplainerText>{" "}
    </div>
  );
}
