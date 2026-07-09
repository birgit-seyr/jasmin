import { useCallback, useMemo } from "react";
import type { CSSProperties, ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useNoteColumn, useSizeOptions, useUnitOptions } from "@hooks/index";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { editableOnlyOnCreate } from "@shared/utils";

import { useAmountUnitSizeColumns } from "./useAmountUnitSizeColumns";
import { useShareArticleColumn } from "./useShareArticleColumn";

const WIDTH_ARTICLE = "30%";
const WIDTH_AMOUNT_UNIT_SIZE = "10%";

// A packing-list row can carry a BACKUP article (the substitute veg planned in
// the BackupModal). When present we render its name / unit / size as a second,
// GREY line inside the SAME cell — so the backup reads as a sub-line of the
// vegetable it backs up, in the right columns.
const BACKUP_SUBLINE_STYLE: CSSProperties = {
  color: "var(--color-text-secondary)",
  fontSize: "0.85em",
  lineHeight: 1.2,
};

export function withBackupSubline(
  main: ReactNode,
  backup: ReactNode,
): ReactNode {
  if (backup === null || backup === undefined || backup === "")
    return main ?? "";
  return (
    <>
      <div>{main}</div>
      <div style={BACKUP_SUBLINE_STYLE}>{backup}</div>
    </>
  );
}

interface UsePackingBaseColumnsOptions {
  /** Which share articles the article-column selector may pick from. */
  shareArticleFilters?: Record<string, unknown>;
  /** PDF width for the trailing note column (depends on how many value columns
   *  precede it, so the caller supplies it). Defaults to 10%. */
  noteWidth?: string;
}

export function usePackingBaseColumns(
  options: UsePackingBaseColumnsOptions = {},
) {
  const { t } = useTranslation();
  const { getUnitLabel } = useUnitOptions();
  const { getSizeLabel } = useSizeOptions();
  const { noteColumn } = useNoteColumn();

  const { shareArticleColumn } = useShareArticleColumn({
    filters: options.shareArticleFilters ?? {
      is_harvest_share_article: true,
      is_active: true,
    },
    showFruitsAndVegs: true,
  });

  const { amountUnitSizeColumns } = useAmountUnitSizeColumns({
    overrides: {
      unit: { disabled: editableOnlyOnCreate },
      size: { disabled: editableOnlyOnCreate },
    },
    showAmount: false,
  });

  const baseColumns = useMemo<EditableColumnConfig<TableRecord>[]>(
    () => [
      {
        ...shareArticleColumn,
        disabled: editableOnlyOnCreate,
        render: (value: unknown, record: TableRecord, index: number) => {
          const original = shareArticleColumn.render
            ? shareArticleColumn.render(value, record, index)
            : ((record.share_article_name as ReactNode) ??
              (value as ReactNode) ??
              "");
          const backup = record?.backup_share_article_name
            ? `${t("commissioning.backup")}: ${record.backup_share_article_name}`
            : null;
          return withBackupSubline(original, backup);
        },
        pdf: {
          include: true,
          width: WIDTH_ARTICLE,
          dataKey: "share_article_name",
          align: "left",
          title: t("commissioning.vegetables_and_fruits"),
        },
      },
      ...amountUnitSizeColumns.map((col): EditableColumnConfig<TableRecord> => {
        const isUnit = col.dataIndex === "unit";
        const isSize = col.dataIndex === "size";
        return {
          ...col,
          render: (value: unknown, record: TableRecord, index: number) => {
            const original = col.render
              ? col.render(value, record, index)
              : ((value as ReactNode) ?? "");
            let backup: ReactNode = null;
            if (record?.backup_share_article_name) {
              if (isUnit && record.backup_share_article_unit) {
                backup = getUnitLabel(
                  record.backup_share_article_unit as string,
                );
              } else if (isSize && record.backup_share_article_size) {
                backup = getSizeLabel(
                  record.backup_share_article_size as string,
                );
              }
            }
            return withBackupSubline(original, backup);
          },
          pdf: {
            include: true,
            width: WIDTH_AMOUNT_UNIT_SIZE,
            align: "center",
            dataKey:
              col.dataIndex === "unit"
                ? "unit_label"
                : col.dataIndex === "size"
                  ? "size_label"
                  : col.dataIndex,
            title: col.title,
          },
        };
      }),
    ],
    [shareArticleColumn, amountUnitSizeColumns, getUnitLabel, getSizeLabel, t],
  );

  const endNoteColumn = useMemo<EditableColumnConfig<TableRecord>>(
    () => ({
      ...noteColumn,
      inputType: "optional",
      disabled: true,
      pdf: {
        include: true,
        width: options.noteWidth ?? "10%",
        dataKey: "note",
        align: "left",
        title: t("commissioning.note"),
      },
    }),
    [noteColumn, options.noteWidth, t],
  );

  const withUnitSizeLabels = useCallback(
    <T extends TableRecord>(rows: T[]): T[] =>
      rows.map((item) => ({
        ...item,
        unit_label: item.unit ? getUnitLabel(item.unit as string) : "",
        size_label: item.size ? getSizeLabel(item.size as string) : "",
      })),
    [getUnitLabel, getSizeLabel],
  );

  return { baseColumns, noteColumn: endNoteColumn, withUnitSizeLabels };
}
