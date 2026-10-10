/**
 * usePlanningAxes resolves every planning grid's days and variations from one
 * date — the Saturday of the ISO week — and orders the variations by the
 * office's sort order, then size.
 */
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const axes = vi.hoisted(() => ({
  days: vi.fn(),
  variations: vi.fn(),
}));

vi.mock("../useShareDeliveryDays", () => ({ useShareDeliveryDays: axes.days }));
vi.mock("../useShareTypeVariations", () => ({ useShareTypeVariations: axes.variations }));

import { usePlanningAxes } from "../usePlanningAxes";

beforeEach(() => {
  vi.clearAllMocks();
  axes.days.mockReturnValue({ shareDeliveryDays: [{ id: "tue" }], toursExist: true, loading: false });
  axes.variations.mockReturnValue({
    shareTypeVariations: [
      { id: "l", size: "L", sort_order: 3 },
      { id: "s", size: "S", sort_order: 1 },
      { id: "m2", size: "XL", sort_order: null },
      { id: "m", size: "M", sort_order: 2 },
      { id: "a", size: "A", sort_order: null },
    ],
    loading: true,
  });
});

describe("usePlanningAxes", () => {
  it("resolves the week to its Saturday for both axes", () => {
    const { result } = renderHook(() =>
      usePlanningAxes({ year: 2026, week: 42, shareOption: "HARVEST_SHARE" }),
    );
    expect(result.current.activeAtDate).toBe("2026-10-17");
    expect(axes.days).toHaveBeenCalledWith({
      active_at_date: "2026-10-17",
      get_delivery_stations: true,
      need_info_on_tours: false,
    });
    expect(axes.variations).toHaveBeenCalledWith({
      physical: true,
      active_at_date: "2026-10-17",
      share_option: "HARVEST_SHARE",
    });
  });

  it("orders the variations by sort order, then size", () => {
    const { result } = renderHook(() =>
      usePlanningAxes({ year: 2026, week: 42, shareOption: "HARVEST_SHARE" }),
    );
    expect(result.current.shareTypeVariations.map((v) => v.id)).toEqual([
      "a",
      "m2",
      "s",
      "m",
      "l",
    ]);
    expect(result.current.toursExist).toBe(true);
    expect(result.current.daysLoading).toBe(false);
    expect(result.current.variationsLoading).toBe(true);
  });

  it("asks for no variations without a share option", () => {
    renderHook(() => usePlanningAxes({ year: 2026, week: 42, shareOption: null }));
    expect(axes.variations).toHaveBeenCalledWith(null);
  });

  it("passes the station and tour switches to the day axis", () => {
    renderHook(() =>
      usePlanningAxes({ year: 2026, week: 42, requireStations: false, needTours: true }),
    );
    expect(axes.days).toHaveBeenCalledWith(
      expect.objectContaining({ get_delivery_stations: false, need_info_on_tours: true }),
    );
  });
});
