/**
 * usePackingModeShareGroups sorts the share types and share options by whether
 * they have a variation packed in bulk, in boxes, or both.
 */
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const queries = vi.hoisted(() => ({
  shareTypes: vi.fn(),
  variations: vi.fn(),
}));

vi.mock("@hooks/useShareTypes", () => ({ useShareTypes: queries.shareTypes }));
vi.mock("@hooks/useAllShareTypeVariations", () => ({
  useAllShareTypeVariations: queries.variations,
}));

import { usePackingModeShareGroups } from "../usePackingModeShareGroups";

beforeEach(() => {
  vi.clearAllMocks();
  queries.shareTypes.mockReturnValue({
    shareTypes: [
      { id: "veg", share_option: "HARVEST_SHARE" },
      { id: "fruit", share_option: "HARVEST_SHARE_FRUIT" },
      { id: "bread", share_option: null },
      { id: null, share_option: "EGGS" },
    ],
    loading: false,
  });
  queries.variations.mockReturnValue({
    shareTypeVariations: [
      { share_type: "veg", is_packed_bulk: false },
      { share_type: "veg", is_packed_bulk: true },
      { share_type: "fruit", is_packed_bulk: false },
      { share_type: "bread", is_packed_bulk: true },
    ],
    loading: false,
  });
});

describe("usePackingModeShareGroups", () => {
  it("groups share types and options by packing mode", () => {
    const { result } = renderHook(() => usePackingModeShareGroups("2026-10-17"));
    expect([...result.current.bulkShareTypeIds].sort()).toEqual(["bread", "veg"]);
    expect([...result.current.boxesShareTypeIds].sort()).toEqual(["fruit", "veg"]);
    expect([...result.current.bulkShareOptions]).toEqual(["HARVEST_SHARE"]);
    expect([...result.current.boxesShareOptions].sort()).toEqual([
      "HARVEST_SHARE",
      "HARVEST_SHARE_FRUIT",
    ]);
    expect(result.current.loading).toBe(false);
  });

  it("asks both queries for the given date", () => {
    renderHook(() => usePackingModeShareGroups("2026-10-17"));
    expect(queries.shareTypes).toHaveBeenCalledWith({ active_at_date: "2026-10-17" });
    expect(queries.variations).toHaveBeenCalledWith(expect.any(Array), {
      active_at_date: "2026-10-17",
    });
  });

  it("is loading while either query loads", () => {
    queries.variations.mockReturnValue({ shareTypeVariations: [], loading: true });
    const { result } = renderHook(() => usePackingModeShareGroups("2026-10-17"));
    expect(result.current.loading).toBe(true);
  });
});
