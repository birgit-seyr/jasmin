import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// The hook's only cross-module dependency is the size-label helper; stub it so
// the test needs neither i18n nor a tenant. No JSX / react-i18next required —
// the hook doesn't call useTranslation.
vi.mock("@hooks/index", () => ({
  useShareTypeVariationSizeOptions: () => ({
    getShareTypeVariationSizeLabel: (size: string) => size || "",
  }),
}));

import {
  useSubscriptionVariationStats,
  VARIATION_PALETTE,
} from "../useSubscriptionVariationStats";

// Deliberately out of numeric order and with a two-digit id, to prove the
// palette order is by numeric id — not array order, not lexicographic.
const variations = [
  { id: "2", share_type_name: "Veg", size: "FULL" },
  { id: "10", share_type_name: "Veg", size: "HALF" },
  { id: "1", share_type_name: "Fruit", size: "FULL" },
];

describe("useSubscriptionVariationStats", () => {
  it("counts on_waiting_list subscriptions in the waiting snapshot", () => {
    const subs = [
      { share_type_variation: "1", quantity: 2, on_waiting_list: true },
      { share_type_variation: "2", quantity: 1, on_waiting_list: true },
      // Cancelled waiting-list entry — excluded.
      {
        share_type_variation: "2",
        quantity: 5,
        on_waiting_list: true,
        cancelled_at: "2026-01-01",
      },
      // Confirmed, open-ended term → active, NOT waiting.
      {
        share_type_variation: "1",
        quantity: 3,
        admin_confirmed: true,
        valid_from: "2000-01-03",
        valid_until: "2099-12-27",
      },
    ];
    const { result } = renderHook(() =>
      useSubscriptionVariationStats(subs, variations),
    );
    expect(result.current.snapshot.waiting.total).toBe(3); // 2 + 1
    expect(result.current.snapshot.waiting.byVariation.get("1")).toBe(2);
    expect(result.current.snapshot.waiting.byVariation.get("2")).toBe(1);
    // The active sub is not swept into the waiting tile.
    expect(result.current.snapshot.active.total).toBe(3);
  });

  it("gives each variation a stable colour regardless of catalogue order", () => {
    const forward = renderHook(() =>
      useSubscriptionVariationStats([], variations),
    ).result.current.variationInfo;
    const reversed = renderHook(() =>
      useSubscriptionVariationStats([], [...variations].reverse()),
    ).result.current.variationInfo;

    for (const id of ["1", "2", "10"]) {
      expect(forward.get(id)?.color).toBe(reversed.get(id)?.color);
    }
    // Numeric-aware id order → 1, 2, 10 map to palette 0, 1, 2 (a lexicographic
    // sort would put "10" before "2" and fail here).
    expect(forward.get("1")?.color).toBe(VARIATION_PALETTE[0]);
    expect(forward.get("2")?.color).toBe(VARIATION_PALETTE[1]);
    expect(forward.get("10")?.color).toBe(VARIATION_PALETTE[2]);
  });
});
