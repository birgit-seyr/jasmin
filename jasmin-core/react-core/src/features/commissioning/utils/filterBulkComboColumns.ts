import type { PackingBoxesMatrixColumn } from "@shared/api/generated/models";

/**
 * Drops box-combination columns whose BASE variation is bulk-packed
 * (``ShareTypeVariation.is_packed_bulk``). Bulk variations belong on the
 * separate bulk packing list, not on tour lists / pickup lists, so they must
 * not surface as a box combination there.
 *
 * Filters on ``base_variation_id`` ONLY: the backend emits a bulk variation as
 * a standalone base combo (``add_ons: []``). Columns with a null base (orphan
 * "no base" groups) and columns whose base is non-bulk are kept — a non-bulk
 * base box may legitimately carry a bulk variation as an add-on, and dropping
 * it would remove a real box.
 */
export function filterBulkComboColumns(
  columns: PackingBoxesMatrixColumn[],
  bulkVariationIds: ReadonlySet<string>,
): PackingBoxesMatrixColumn[] {
  return columns.filter(
    (column) =>
      column.base_variation_id == null ||
      !bulkVariationIds.has(String(column.base_variation_id)),
  );
}
