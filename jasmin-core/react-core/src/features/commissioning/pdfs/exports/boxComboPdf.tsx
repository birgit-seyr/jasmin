import { StyleSheet, Text, View } from "@react-pdf/renderer";
import type { ReactNode } from "react";
import type { TFunction } from "i18next";

import type { PackingBoxesMatrixColumn } from "@shared/api/generated/models";
import { getShareTypeVariationSizeLabelPure } from "@hooks/index";
import { listStyles } from "./listPdfBase";
import { pdfTheme } from "./pdfTheme";

/**
 * Shared PDF building blocks for the box-combination matrices (packing boxes,
 * delivery-stations overview): a combination column header (base size + add-on
 * badges) and the group-by-base-share_type helper for the parent header row.
 * Sizes use ``getShareTypeVariationSizeLabelPure`` — the same labels the
 * on-screen ``BoxCombinationLabel`` uses (covers every SizeOptions code).
 */

export const boxComboStyles = StyleSheet.create({
  comboBase: { fontWeight: 700 },
  comboAddons: { fontSize: 6, color: "#555" },
  // The brand-green vertical rules that frame each base-share_type group —
  // the SINGLE source for every box-combination matrix (packing boxes,
  // delivery overview / details). Left rule on a group's first column, right
  // rule on its last, so a group is boxed on both sides.
  groupBorderLeft: {
    borderLeftWidth: 1.5,
    borderLeftColor: pdfTheme.colors.brand,
  },
  groupBorderRight: {
    borderRightWidth: 1.5,
    borderRightColor: pdfTheme.colors.brand,
  },
});

/** For each column key, whether it is the LEFT (first) and/or RIGHT (last)
 *  column of its base-share_type group — drives the green group rules so a
 *  group is framed on both sides. Columns arrive already grouped. */
export function computeGroupEdges(
  groups: ComboGroup[],
): Map<string, { left: boolean; right: boolean }> {
  const edges = new Map<string, { left: boolean; right: boolean }>();
  for (const group of groups) {
    group.cols.forEach((col, index) => {
      edges.set(col.key, {
        left: index === 0,
        right: index === group.cols.length - 1,
      });
    });
  }
  return edges;
}

/** The green group rules for one column ``key`` (from the precomputed group
 *  edges): left rule on a group's first column, right rule on its last. Spread
 *  the result into a cell's ``style`` array — the single application of the
 *  green group rules across all three box-combination matrices. */
export function groupEdgeStyles(
  groupEdges: Map<string, { left: boolean; right: boolean }>,
  key: string,
) {
  const edge = groupEdges.get(key);
  return [
    edge?.left ? boxComboStyles.groupBorderLeft : {},
    edge?.right ? boxComboStyles.groupBorderRight : {},
  ];
}

/** A box/share count for a matrix cell: blank when the value is empty, null,
 *  or zero; otherwise the integer as a string. The superset of the per-matrix
 *  ``formatCount``/``formatAmount`` copies (integer box counts, no currency). */
export function formatComboCount(value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return "";
  return String(n);
}

/** Header label for one combination: base size + one "SHORT·size" per add-on. */
export function ComboHeader({
  column,
  t,
}: {
  column: PackingBoxesMatrixColumn;
  t: TFunction;
}) {
  const base = column.base_variation_id
    ? getShareTypeVariationSizeLabelPure(column.base_size, t)
    : "—";
  return (
    <View>
      <Text style={boxComboStyles.comboBase}>{base}</Text>
      {column.add_ons.length > 0 && (
        <Text style={boxComboStyles.comboAddons}>
          {column.add_ons
            .map(
              (addOn) =>
                `${addOn.share_type_short_name}·${getShareTypeVariationSizeLabelPure(addOn.size, t)}`,
            )
            .join(" ")}
        </Text>
      )}
    </View>
  );
}

// A4 content width = page width − 2×40pt horizontal padding (see
// ``listPdfBase.page.paddingHorizontal = spacing.page = 40``).
const A4_PORTRAIT_CONTENT = 595.28 - 80; // ≈ 515pt
const A4_LANDSCAPE_CONTENT = 841.89 - 80; // ≈ 762pt

export type PdfOrientation = "portrait" | "landscape";

/**
 * Per-combination column width (pt) for a page, given the DOCUMENT's chosen
 * orientation. Combos are never stretched past ``comboIdeal`` — when a page has
 * few combos the flex name/note column absorbs the slack instead — and shrink
 * to fill exactly when there are many (the flex column holds at
 * ``flexMinWidth``), so the table always fits the page at any combo count.
 */
export function comboColumnWidth({
  orientation,
  comboCount,
  fixedWidth,
  flexMinWidth,
  // A bit wider than the old 52pt: few-combo pages read better and the first
  // column stays fixed (the slack sits on the right instead of stretching it).
  comboIdeal = 64,
}: {
  orientation: PdfOrientation;
  comboCount: number;
  /** Total pt of the fixed (non-combo, non-flex) columns. */
  fixedWidth: number;
  /** Min pt reserved for the flex name/note column. */
  flexMinWidth: number;
  comboIdeal?: number;
}): number {
  const content =
    orientation === "portrait" ? A4_PORTRAIT_CONTENT : A4_LANDSCAPE_CONTENT;
  const perCombo =
    (content - fixedWidth - flexMinWidth) / Math.max(comboCount, 1);
  // Cap at the ideal so few combos don't stretch (the flex name/note column
  // absorbs the slack instead); otherwise fill exactly so the table always fits
  // the page and the flex column keeps its ``flexMinWidth`` (combos shrink, at
  // extreme counts, rather than overflowing or collapsing the flex column).
  return perCombo >= comboIdeal ? comboIdeal : perCombo;
}

/**
 * Choose the page orientation from the WIDEST page (``maxComboCount``) so every
 * page of the document shares one orientation: portrait while its combos still
 * fit at a readable ``comboMin``, else landscape.
 */
export function pickComboOrientation({
  maxComboCount,
  fixedWidth,
  flexMinWidth,
  comboMin = 42,
}: {
  maxComboCount: number;
  fixedWidth: number;
  flexMinWidth: number;
  comboMin?: number;
}): PdfOrientation {
  const perComboPortrait =
    (A4_PORTRAIT_CONTENT - fixedWidth - flexMinWidth) /
    Math.max(maxComboCount, 1);
  return perComboPortrait >= comboMin ? "portrait" : "landscape";
}

export interface ComboGroup {
  id: string;
  name: string;
  cols: PackingBoxesMatrixColumn[];
}

/** Group consecutive combination columns by their base share_type (columns
 * arrive already sorted by share_type), so a header can render a parent row
 * with the share_type short_name spanning its combinations. */
export function groupComboColumns(
  columns: PackingBoxesMatrixColumn[],
  t: TFunction,
): ComboGroup[] {
  const groups: ComboGroup[] = [];
  for (const column of columns) {
    const id = column.base_share_type_id ?? "__none__";
    const name = column.base_variation_id
      ? column.base_share_type_short_name
      : t("commissioning.no_base_combination");
    const last = groups[groups.length - 1];
    if (last && last.id === id) last.cols.push(column);
    else groups.push({ id, name, cols: [column] });
  }
  return groups;
}

/**
 * The box-combination matrices' PARENT header row: each base share_type name
 * spans its combination columns, framed by the green group rules on both sides.
 * The leading/trailing fixed cells (article/unit/size on the left, note/tick on
 * the right) differ per matrix, so callers pass them as ``leading``/``trailing``
 * slots. ``thinBorderBottom`` adds the slim 0.5pt divider the overview/details
 * matrices use to separate this row from the sub-header (the packing-boxes
 * matrix leaves it off). Kept ``fixed`` so it repeats on every printed page.
 */
export function ComboGroupHeaderRow({
  groups,
  comboWidth,
  leading,
  trailing,
  thinBorderBottom = false,
}: {
  groups: ComboGroup[];
  comboWidth: number;
  leading?: ReactNode;
  trailing?: ReactNode;
  thinBorderBottom?: boolean;
}) {
  return (
    <View
      style={
        thinBorderBottom
          ? [listStyles.tableHeaderShaded, { borderBottomWidth: 0.5 }]
          : listStyles.tableHeaderShaded
      }
      fixed
    >
      {leading}
      {groups.map((group) => (
        <View
          key={group.id}
          style={[
            listStyles.cell,
            listStyles.cellCenter,
            { width: comboWidth * group.cols.length },
            boxComboStyles.groupBorderLeft,
            boxComboStyles.groupBorderRight,
          ]}
        >
          <Text style={boxComboStyles.comboBase}>{group.name}</Text>
        </View>
      ))}
      {trailing}
    </View>
  );
}

/**
 * The box-combination matrices' COLUMN sub-header row: one ``ComboHeader``
 * (base size + add-on badges) per combination column, each carrying the green
 * group rules for its base-share_type group. The leading/trailing fixed cells
 * differ per matrix, so callers pass them as ``leading``/``trailing`` slots.
 * Kept ``fixed`` so it repeats on every printed page.
 */
export function ComboColumnHeaderRow({
  columns,
  comboWidth,
  groupEdges,
  t,
  leading,
  trailing,
}: {
  columns: PackingBoxesMatrixColumn[];
  comboWidth: number;
  groupEdges: Map<string, { left: boolean; right: boolean }>;
  t: TFunction;
  leading?: ReactNode;
  trailing?: ReactNode;
}) {
  return (
    <View style={listStyles.tableHeaderShaded} fixed>
      {leading}
      {columns.map((column) => (
        <View
          key={column.key}
          style={[
            listStyles.cell,
            { width: comboWidth },
            listStyles.cellCenter,
            ...groupEdgeStyles(groupEdges, column.key),
          ]}
        >
          <ComboHeader column={column} t={t} />
        </View>
      ))}
      {trailing}
    </View>
  );
}
