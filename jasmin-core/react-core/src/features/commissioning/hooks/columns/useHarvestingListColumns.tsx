/**
 * Column factory for the HarvestingList page — both the on-screen
 * table (office grouped layout / gardener flat layout) and the PDF
 * (always flat). Pulled out of the page component so the page only
 * wires state + data; every column shape lives here.
 */

import type { ReactNode } from "react";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import type {
  EditableColumnConfig,
  EditableColumnPdfConfig,
  InputType,
  SelectOption,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { ToolTipIcon } from "@shared/ui";
import { amountCellText, editableOnlyOnCreate } from "@shared/utils";
import { useCrates } from "../useCrates";
import { useTenant } from "@hooks/configuration/useTenant";
import { useNumberFormat } from "@hooks/useNumberFormat";
import { useVegetableSizeOptions } from "@hooks/useVegetableSizeOptions";
import { useAmountUnitSizeColumns } from "./useAmountUnitSizeColumns";
import { useNoteColumn } from "@hooks/columns/useNoteColumn";
import { useShareArticleColumn } from "./useShareArticleColumn";

const widthShareArticle = "24%";
const widthAmountCombined = "15%";
const widthAmountPerPu = "10%";
const widthHarvestingCrate = "8%";
const widthNote = "22%";

/** Pulls the two computed note pieces (free-form + plot/bed line) off a row.
 *  Returned as an array so callers can render them as separate <div>s or join
 *  them with "\n" for the PDF. */
function getNoteLines(record: TableRecord): string[] {
  const lines: string[] = [];
  if (record.computed_note_line)
    lines.push(record.computed_note_line as string);
  if (record.computed_plot_line)
    lines.push(record.computed_plot_line as string);
  return lines;
}

const shareArticleFilters = {
  is_harvest_share_article: "true",
  is_active: "true",
  is_purchased: "false",
};

/** Combined "amount + amount/PU" cell, used by both the gardener flat and the
 *  office grouped layouts. */
function renderCombinedCell(
  className: string,
  suffix: "" | "_share_content" | "_order_content",
) {
  return (_: unknown, record: TableRecord) => {
    const totalText = record[`computed_total_amount_text${suffix}`] as string;
    const puText = record[`computed_amount_pu_text${suffix}`] as string;
    return (
      <div className={className}>
        {totalText}
        {puText && <br />}
        {puText}
      </div>
    );
  };
}

/** ``columns`` without the resellers' amounts (``…_order_content``), for a
 *  farm that doesn't sell to resellers. An amount group left with its share
 *  amount alone becomes that one column, under the group's title and as wide
 *  as the pair was, rather than a group with a single "share content" child. */
function withoutResellerColumns(
  columns: EditableColumnConfig<TableRecord>[],
): EditableColumnConfig<TableRecord>[] {
  return columns.flatMap((column) => {
    if (column.dataIndex.endsWith("_order_content")) return [];
    if (!column.children) return [column];
    const children = withoutResellerColumns(column.children);
    if (children.length !== 1) return [{ ...column, children }];
    const [shareAmount] = children;
    return [
      {
        ...shareAmount,
        title: column.title,
        width: pairWidth(shareAmount.width),
      },
    ];
  });
}

/** The width of a share/order pair, whose two columns share one width. */
function pairWidth(width: EditableColumnConfig<TableRecord>["width"]) {
  return typeof width === "string" && width.endsWith("em")
    ? `${2 * parseFloat(width)}em`
    : width;
}

export function useHarvestingListColumns({
  isMobile,
  isGardenerView,
  isPastDay = false,
}: {
  isMobile: boolean;
  isGardenerView: boolean;
  /** A day before today, whose additional amounts stay as they are. */
  isPastDay?: boolean;
}) {
  const { t } = useTranslation();
  const { getSetting } = useTenant();
  const { getVegetableSizeLabel } = useVegetableSizeOptions();
  const { crates } = useCrates();
  const { noteColumn } = useNoteColumn();
  const { format } = useNumberFormat();
  const sellsToResellers = Boolean(getSetting("sells_to_resellers", true));

  const { shareArticleColumn, handleUnitChange } = useShareArticleColumn({
    filters: shareArticleFilters,
    showFruitsAndVegs: true,
    autofillContext: "harvest",
    overrides: {
      ...(isGardenerView && {
        render: (text: unknown, record: Record<string, unknown>) => {
          const sizeLabel =
            record.size && record.size !== "M"
              ? ` (${getVegetableSizeLabel(record.size as string)})`
              : "";
          return `${text}${sizeLabel}`;
        },
      }),
    },
  });

  const { amountUnitSizeColumns } = useAmountUnitSizeColumns({
    showAmount: false,
    overrides: {
      unit: {
        onFieldChange: handleUnitChange,
        disabled: editableOnlyOnCreate,
        hidden: isMobile || isGardenerView,
      },
      size: {
        disabled: editableOnlyOnCreate,
        hidden: isMobile || isGardenerView,
      },
    },
  });

  // Memoize so these stable JSX titles don't invalidate the
  // makeShareOrderChildren useCallback (which depends on them) on every render.
  const titleShareContent: ReactNode = useMemo(
    () => (
      <span className="harvesting-list-content-title">
        {t("commissioning.title_share_content")}
      </span>
    ),
    [t],
  );

  const titleOrderContent: ReactNode = useMemo(
    () => (
      <span className="harvesting-list-content-title">
        {t("commissioning.title_order_content")}
      </span>
    ),
    [t],
  );

  // Helper: build the share/order pair of child columns for a single
  // metric. Both children have the exact same shape; only the dataIndex
  // suffix and color differ.
  const makeShareOrderChildren = useCallback(
    (
      base: string,
      opts: {
        width?: string;
        inputType?: InputType;
        readOnly?: boolean;
        bold?: boolean;
        renderText?: (record: TableRecord, key: string) => ReactNode;
        pdf?: EditableColumnPdfConfig;
      } = {},
    ) => {
      const {
        width = "4.5em",
        inputType = "text",
        readOnly,
        bold,
        renderText,
        pdf,
      } = opts;

      const buildChild = (
        suffix: "_share_content" | "_order_content",
        title: ReactNode,
        colorClassName: string,
        extra: Partial<EditableColumnConfig<TableRecord>> = {},
      ): EditableColumnConfig<TableRecord> => {
        const dataIndex = `${base}${suffix}`;
        const spanClassName = bold
          ? `${colorClassName} text-bold`
          : colorClassName;
        const render = renderText
          ? (_: unknown, record: TableRecord) => (
              <span className={spanClassName}>
                {renderText(record, dataIndex)}
              </span>
            )
          : (value: unknown, record: TableRecord) => (
              <span className={spanClassName}>
                {amountCellText(value, record.unit as string, format)}
              </span>
            );

        return {
          title,
          dataIndex,
          inputType,
          required: false,
          width,
          align: "center",
          disabled: inputType === "text",
          hidden: isMobile || isGardenerView,
          ...(readOnly ? { readOnly: true } : {}),
          render,
          pdf: pdf ?? { include: false },
          ...extra,
        };
      };

      return [
        buildChild("_share_content", titleShareContent, "text-share-content", {
          className: "column-group-start",
          hideInModal: inputType === "text",
        }),
        buildChild("_order_content", titleOrderContent, "text-order-content", {
          hideInModal: inputType === "text",
        }),
      ];
    },
    [isMobile, isGardenerView, titleShareContent, titleOrderContent, format],
  );

  // Flat version (gardener view): two stand-alone columns, no grouping.

  const columnsAmountsSeparateFlat = useMemo<
    EditableColumnConfig<TableRecord>[]
  >(
    () =>
      (
        [
          {
            suffix: "_share_content",
            colorClassName: "text-share-content",
            titleSuffix: t("commissioning.title_share_content"),
            pdfTitle: t("commissioning.title_share_content"),
            className: "column-group-start",
          },
          {
            suffix: "_order_content",
            colorClassName: "text-order-content",
            titleSuffix: t("commissioning.title_order_content"),
            pdfTitle: t("commissioning.title_order_content"),
            className: undefined as string | undefined,
          },
        ] as const
      ).map(({ suffix, colorClassName, titleSuffix, pdfTitle, className }) => ({
        // Without resellers the share amount is the only one, so it needs no
        // "share content" qualifier.
        title: sellsToResellers ? (
          <>
            {t("commissioning.amount_harvesting_list")}
            <br />({titleSuffix})
          </>
        ) : (
          t("commissioning.amount_harvesting_list")
        ),
        dataIndex: `computed_amount_combined${suffix}`,
        key: `amount${suffix}_flat`,
        inputType: "text",
        required: false,
        width: "9em",
        align: "center",
        disabled: true,
        ...(className ? { className } : {}),
        render: renderCombinedCell(colorClassName, suffix),
        pdf: {
          include: true,
          width: widthAmountCombined,
          align: "center",
          title: sellsToResellers
            ? pdfTitle
            : t("commissioning.amount_harvesting_list"),
          dataKey: `computed_amount_combined${suffix}`,
        },
      })),
    [t, sellsToResellers],
  );

  // Office view: grouped columns with share/order children.

  // Group parents carry a ``dataIndex`` mirroring their ``key`` purely to
  // satisfy the column config shape — AntD ignores it on columns with
  // ``children`` (same convention as useDeliveryDayColumns).
  const columnsAmountsSeparate = useMemo<EditableColumnConfig<TableRecord>[]>(
    () => [
      {
        title: <>{t("commissioning.theoretical_harvest")}</>,
        dataIndex: "theoretical_harvest_amount",
        key: "theoretical_harvest_amount",
        className: "column-group-start",
        children: makeShareOrderChildren("theoretical_harvest_amount"),
      },
      {
        title: <>{t("commissioning.still_in_stock")}</>,
        dataIndex: "computed_still_in_stock",
        key: "computed_still_in_stock",
        className: "column-group-start",
        children: makeShareOrderChildren("computed_still_in_stock", {
          readOnly: true,
        }),
      },
      {
        title: <>{t("commissioning.to_harvest")}</>,
        dataIndex: "computed_to_harvest",
        key: "computed_to_harvest",
        className: "column-group-start",
        children: makeShareOrderChildren("computed_to_harvest", {
          readOnly: true,
        }),
      },
      {
        title: (
          <>
            {t("commissioning.additional_theoretical_harvest")}
            <ToolTipIcon title={t("tooltip.additional_theoretical_harvest")} />
          </>
        ),
        dataIndex: "amount",
        key: "amount",
        className: "column-group-start",
        // Edited as ``amount_share_content`` / ``amount_order_content``, shown
        // from the matching ``additional_theoretical_harvest_amount_*``.
        children: makeShareOrderChildren("amount", {
          inputType: "negative_integer",
          readOnly: isPastDay,
          bold: true,
          renderText: (record, key) =>
            amountCellText(
              record[key.replace("amount", "additional_theoretical_harvest_amount")],
              record.unit as string,
              format,
            ),
        }),
      },
      {
        title: <>{t("commissioning.amount_harvesting_list")}</>,
        dataIndex: "amount_harvesting_list",
        key: "amount_harvesting_list",
        className: "column-group-start",
        children: (
          [
            {
              suffix: "_share_content" as const,
              colorClassName: "text-share-content",
              className: "column-group-start",
            },
            {
              suffix: "_order_content" as const,
              colorClassName: "text-order-content",
              className: undefined as string | undefined,
            },
          ] as const
        ).map(({ suffix, colorClassName, className }) => ({
          title:
            suffix === "_share_content" ? titleShareContent : titleOrderContent,
          inputType: "text",
          dataIndex: `computed_amount_combined${suffix}`,
          required: false,
          width: "8em",
          align: "center",
          disabled: true,
          ...(className ? { className } : {}),
          render: renderCombinedCell(colorClassName, suffix),
          pdf: {
            include: true,
            width: widthAmountCombined,
            align: "center",
            title: t("commissioning.amount"),
            dataKey: `computed_amount_combined${suffix}`,
          },
        })),
      },
    ],
    [t, makeShareOrderChildren, titleShareContent, titleOrderContent, format, isPastDay],
  );

  const columns: EditableColumnConfig<TableRecord>[] = useMemo(
    () => [
      {
        ...shareArticleColumn,
        disabled: editableOnlyOnCreate,
        pdf: {
          include: true,
          width: widthShareArticle,
          align: "left",
          dataKey: "computed_article_with_size",
          title: t("commissioning.vegetables_and_fruits"),
        },
      },
      ...amountUnitSizeColumns.map((col) => ({
        ...col,
        pdf: { include: false },
      })),
      ...(isGardenerView ? columnsAmountsSeparateFlat : columnsAmountsSeparate),
      {
        title: t("commissioning.per_pu"),
        dataIndex: "amount_per_pu",
        key: "amount_per_pu",
        inputType: "positive_decimal2",
        required: false,
        align: "center",
        width: "8em",
        className: "column-group-start",
        render: (_: unknown, record: TableRecord) =>
          (record.computed_amount_per_pu_text as string) ? (
            <div className="text-hint-md">
              {record.computed_amount_per_pu_text as string}
            </div>
          ) : null,
        // ``style`` is consumed by pdfColumns' PdfColumn but isn't declared on
        // EditableColumnPdfConfig — the cast keeps the extra key.
        pdf: {
          include: true,
          width: widthAmountPerPu,
          align: "center",
          dataKey: "computed_amount_per_pu_text",
          style: {
            fontSize: 8,
            color: "var(--color-text-secondary)",
          },
        } as EditableColumnPdfConfig,
      },

      {
        title: (
          <>
            {t("commissioning.harvesting_crate")}
            <ToolTipIcon title={t("tooltip.harvesting_crate_forecast")} />
          </>
        ),
        dataIndex: "harvesting_crate_name",
        key: "harvesting_crate_name",
        inputType: "select",
        options: crates,
        required: false,
        width: "8em",
        className: "column-group-start",
        foreignKey: {
          valueField: "harvesting_crate",
          displayField: "harvesting_crate_name",
        },
        pdf: {
          include: true,
          width: widthHarvestingCrate,
          align: "center",
          dataKey: "harvesting_crate_name",
          title: t("commissioning.harvesting_crate_short"),
        },
      },

      {
        ...noteColumn,
        inputType: "optional",
        className: "column-group-start",
        disabled: isMobile || isGardenerView,
        render: (_: unknown, record: TableRecord) => (
          <div>
            {getNoteLines(record).map((line, i) => (
              <div key={i} className="text-hint-md">
                {line}
              </div>
            ))}
          </div>
        ),
        // ``render`` is consumed by pdfColumns' PdfColumn but isn't declared on
        // EditableColumnPdfConfig — the cast keeps the extra key.
        pdf: {
          include: true,
          width: widthNote,
          align: "left",
          title: t("commissioning.note"),
          render: (record: TableRecord) => getNoteLines(record).join("\n"),
        } as EditableColumnPdfConfig,
      },
    ],
    [
      shareArticleColumn,
      amountUnitSizeColumns,
      isGardenerView,
      isMobile,
      t,
      crates,
      noteColumn,
      columnsAmountsSeparate,
      columnsAmountsSeparateFlat,
    ],
  );

  // PDF always uses gardener-view (flat) columns for readability

  const pdfColumns: EditableColumnConfig<TableRecord>[] = useMemo(
    () => [
      {
        ...shareArticleColumn,
        pdf: {
          include: true,
          width: widthShareArticle,
          align: "left",
          dataKey: "computed_article_with_size",
          title: t("commissioning.vegetables_and_fruits"),
        },
      },
      ...columnsAmountsSeparateFlat,
      // PDF-only stubs: ``title``/``dataIndex`` are never rendered on screen —
      // the ``pdf`` block (dataKey / render / tickBox) drives the PDF cells.
      {
        title: null,
        dataIndex: "computed_amount_per_pu_text",
        key: "amount_per_pu_pdf",
        pdf: {
          include: true,
          width: widthAmountPerPu,
          align: "center",
          dataKey: "computed_amount_per_pu_text",
          title: t("commissioning.per_pu"),
          style: { fontSize: 8, color: "var(--color-text-secondary)" },
        } as EditableColumnPdfConfig,
      },
      {
        title: null,
        dataIndex: "harvesting_crate_name",
        key: "harvesting_crate_pdf",
        pdf: {
          include: true,
          width: widthHarvestingCrate,
          align: "center",
          dataKey: "harvesting_crate_name",
          title: t("commissioning.harvesting_crate_short"),
        },
      },
      {
        title: null,
        dataIndex: "",
        key: "note_pdf",
        // ``render`` is consumed by pdfColumns' PdfColumn but isn't declared on
        // EditableColumnPdfConfig — the cast keeps the extra key.
        pdf: {
          include: true,
          // Without resellers the note takes the resellers' amount's width too.
          width: sellsToResellers
            ? widthNote
            : `${parseFloat(widthNote) + parseFloat(widthAmountCombined)}%`,
          align: "left",
          title: t("commissioning.note"),
          render: (record: TableRecord) => getNoteLines(record).join("\n"),
        } as EditableColumnPdfConfig,
      },
      {
        title: null,
        dataIndex: "",
        key: "done_pdf",
        pdf: {
          include: true,
          width: "6%",
          align: "center",
          title: "✓",
          tickBox: true,
        },
      },
    ],
    [shareArticleColumn, columnsAmountsSeparateFlat, sellsToResellers, t],
  );

  return useMemo(
    () =>
      sellsToResellers
        ? { columns, pdfColumns }
        : {
            columns: withoutResellerColumns(columns),
            pdfColumns: withoutResellerColumns(pdfColumns),
          },
    [sellsToResellers, columns, pdfColumns],
  );
}
