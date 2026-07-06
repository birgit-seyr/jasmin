import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useCommissioningHarvestSharePlanningList } from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningHarvestSharePlanningListParams,
  HarvestSharePlanningRow,
  ShareTypeEnum,
} from "@shared/api/generated/models";
import { WeekSelector } from "@shared/selectors";
import { SharesDeliveryDaySelector } from "@features/commissioning/selectors";
import { EditableTable, READ_ONLY_PERMISSION } from "@shared/tables";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { MobileStack } from "@shared/ui";
import {
  dayPlannedAmountKey,
  useAmountUnitSizeColumns,
  usePackingModeShareGroups,
  useShareArticleColumn,
} from "@features/commissioning/hooks";
import {
  useIsMobile,
  useSizeOptions,
  useTenant,
  useUnitOptions,
} from "@hooks/index";
import { formatWeekLabel, generatePdfFilename } from "@shared/utils";
import { CommissioningListPackingPDFGenerator } from "@features/commissioning/pdfs";

const currentYear = dayjs().year();
const currentWeek = dayjs().isoWeek();

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
    const amount = rawAmount != null ? parseFloat(String(rawAmount)) : 0;
    if (!amount || amount <= 0) continue;
    const id = String(row.id);
    result.push({
      key: id,
      id,
      share_article: String(row.share_article ?? ""),
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
  deliveryDayId: string | null;
  /** Reports this option's resolved rows up to the parent so they can be
   *  collected into the PDF (each table owns its own fetch). */
  onRowsChange?: (shareOption: string, rows: PackingRow[]) => void;
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
  deliveryDayId,
  onRowsChange,
}: ShareOptionPackingTableProps) {
  const listParams = useMemo<CommissioningHarvestSharePlanningListParams>(
    () => ({
      year,
      // Always a valid number for the type; the query is disabled below when
      // the week is actually cleared, so this fallback never hits the wire.
      delivery_week: week ?? currentWeek,
      // shareOption prop is a string; the list param is now the generated enum.
      share_option: shareOption as ShareTypeEnum,
      is_past: false,
    }),
    [year, week, shareOption],
  );

  const { data: rawData, isFetching } =
    useCommissioningHarvestSharePlanningList<
      (HarvestSharePlanningRow & Record<string, unknown>)[]
    >(listParams, { query: { enabled: week !== null } });

  const rows = useMemo(
    () => buildRows(rawData, deliveryDayId),
    [rawData, deliveryDayId],
  );

  useEffect(() => {
    onRowsChange?.(shareOption, rows);
  }, [shareOption, rows, onRowsChange]);

  return (
    <section className="commissioning-list-packing-section">
      {showHeading && (
        <h3 className="commissioning-list-packing-section__heading">{label}</h3>
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
  const { bulkShareOptions, boxesShareOptions } = usePackingModeShareGroups();

  const [selectedYear, setSelectedYear] = useState(currentYear);
  const [selectedWeek, setSelectedWeek] = useState<number | null>(currentWeek);
  const [selectedDeliveryDayId, setSelectedDeliveryDayId] = useState<
    string | null
  >(null);

  // Same column hooks the other harvest lists use, so the article / unit /
  // size cells render and align identically. Everything is read-only here
  // (``record.key`` is always a real id, never the -1 "new row" sentinel).
  const { shareArticleColumn } = useShareArticleColumn({
    filters: shareArticleFilters,
    showFruitsAndVegs: true,
    articleDefaults: "harvest",
  });

  const { amountUnitSizeColumns } = useAmountUnitSizeColumns({
    overrides: {
      unit: { disabled: (record: TableRecord) => record.key !== -1 },
      size: { disabled: (record: TableRecord) => record.key !== -1 },
    },
    showAmount: false,
  });

  const columns = useMemo<EditableColumnConfig<TableRecord>[]>(() => {
    const totalAmountColumn: EditableColumnConfig<TableRecord> = {
      title: t("commissioning.total_amount"),
      dataIndex: "total_amount",
      key: "total_amount",
      inputType: "positive_decimal2",
      align: "right",
      width: "10em",
      disabled: true,
      render: (value: unknown) => {
        const numeric = Number(value);
        if (!Number.isFinite(numeric)) return "";
        return Number.isInteger(numeric) ? String(numeric) : numeric.toFixed(2);
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
  }, [t, shareArticleColumn, amountUnitSizeColumns]);

  // Every active share option (bulk or boxed), sorted for a stable render
  // order — the packing list totals what's needed across all of them.
  const shareOptionValues = useMemo(
    () =>
      Array.from(new Set([...bulkShareOptions, ...boxesShareOptions])).sort(),
    [bulkShareOptions, boxesShareOptions],
  );

  // Each table owns its own fetch, so collect their rows here to build the
  // PDF. ``handleRows`` is stable and bails when a table reports the same
  // (memoised) rows reference, so it can't loop.
  const isMobile = useIsMobile();
  const { getUnitLabel } = useUnitOptions();
  const { getSizeLabel } = useSizeOptions();
  const { getSetting } = useTenant();
  // Mirror the on-screen size column (``useAmountUnitSizeColumns``): hidden
  // unless the tenant's ``show_size_column`` setting is truthy.
  const showSize = Boolean(getSetting("show_size_column"));
  const [rowsByOption, setRowsByOption] = useState<
    Record<string, PackingRow[]>
  >({});
  const handleRows = useCallback((shareOption: string, rows: PackingRow[]) => {
    setRowsByOption((prev) =>
      prev[shareOption] === rows ? prev : { ...prev, [shareOption]: rows },
    );
  }, []);

  const pdfGroups = useMemo(
    () =>
      shareOptionValues
        .map((value) => ({
          label: t(`commissioning.share_option.${value}`),
          rows: (rowsByOption[value] ?? []).map((row) => ({
            id: row.id,
            share_article_name: row.share_article_name,
            unit_label: row.unit ? getUnitLabel(row.unit) : "",
            size_label:
              row.size && row.size !== "M" ? getSizeLabel(row.size) : "",
            total_amount_text: Number.isInteger(row.total_amount)
              ? String(row.total_amount)
              : row.total_amount.toFixed(2),
          })),
        }))
        .filter((group) => group.rows.length > 0),
    [shareOptionValues, rowsByOption, t, getUnitLabel, getSizeLabel],
  );

  const generateFilename = useMemo(
    () =>
      generatePdfFilename([
        t("commissioning.commissioning_list_packing"),
        selectedYear,
        formatWeekLabel(selectedWeek, t),
      ]),
    [selectedYear, selectedWeek, t],
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
            year={selectedYear}
            week={selectedWeek}
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
          label={t(`commissioning.share_option.${value}`)}
          showHeading={shareOptionValues.length > 1}
          columns={columns}
          year={selectedYear}
          week={selectedWeek}
          deliveryDayId={selectedDeliveryDayId}
          onRowsChange={handleRows}
        />
      ))}
    </div>
  );
}
