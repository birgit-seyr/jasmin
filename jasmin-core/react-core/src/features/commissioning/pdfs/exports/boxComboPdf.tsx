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
