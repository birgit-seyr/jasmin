/**
 * filterBulkComboColumns drops a box combination only when its base variation
 * is packed in bulk; a boxed base carrying a bulk add-on is a real box.
 */
import { describe, expect, it } from "vitest";

import type { PackingBoxesMatrixColumn } from "@shared/api/generated/models";

import { filterBulkComboColumns } from "../filterBulkComboColumns";

const column = (
  key: string,
  baseVariationId: string | null,
  addOns: PackingBoxesMatrixColumn["add_ons"] = [],
): PackingBoxesMatrixColumn => ({
  key,
  base_variation_id: baseVariationId,
  base_size: "M",
  base_sort_order: 1,
  base_share_type_id: "st-1",
  base_share_type_name: "Vegetables",
  base_share_type_short_name: "Veg",
  base_share_type_sort_index: 1,
  add_ons: addOns,
  count: 3,
});

describe("filterBulkComboColumns", () => {
  const bulk = new Set(["var-bulk"]);

  it("drops a column whose base variation is packed in bulk", () => {
    const kept = filterBulkComboColumns(
      [column("box", "var-box"), column("bulk", "var-bulk")],
      bulk,
    );
    expect(kept.map((c) => c.key)).toEqual(["box"]);
  });

  it("keeps a boxed base that carries a bulk add-on", () => {
    const addOn = {
      variation_id: "var-bulk",
      size: "M",
      sort_order: 1,
      share_type_id: "st-2",
      share_type_short_name: "Fruit",
      share_type_sort_index: 2,
    };
    const kept = filterBulkComboColumns([column("box+bulk", "var-box", [addOn])], bulk);
    expect(kept).toHaveLength(1);
  });

  it("keeps a column without a base variation", () => {
    expect(filterBulkComboColumns([column("orphan", null)], bulk)).toHaveLength(1);
  });

});
