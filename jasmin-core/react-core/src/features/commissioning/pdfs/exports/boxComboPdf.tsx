import { StyleSheet, Text, View } from "@react-pdf/renderer";
import type { TFunction } from "i18next";

import type { PackingBoxesMatrixColumn } from "@shared/api/generated/models";
import { getShareTypeVariationSizeLabelPure } from "@hooks/index";

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
});

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
  comboIdeal = 52,
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
