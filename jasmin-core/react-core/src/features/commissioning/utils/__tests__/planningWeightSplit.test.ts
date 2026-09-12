import { describe, expect, it } from "vitest";

import {
  countDeliveryWeeks,
  suggestPerShareAmounts,
  type VariationWeightCount,
} from "../planningWeightSplit";

// These fixtures MIRROR apps/commissioning/tests/tests_utils/test_forecast_distribution.py.
// The Python split takes a per-delivery forecast_amount; here that's
// targetTotal / numFilteredWeeks, so weeks=1 makes targetTotal == forecast_amount.
const S_M = (
  countS: number,
  countM: number,
): VariationWeightCount[] => [
  { variationId: "S", averageWeight: 1, subscriberCount: countS },
  { variationId: "M", averageWeight: 2, subscriberCount: countM },
];

describe("suggestPerShareAmounts", () => {
  it("scales each size with its weight (mirror: {S:5.0, M:10.0})", () => {
    const r = suggestPerShareAmounts(100, 1, S_M(10, 5));
    expect(r.amountsByVariation).toEqual({ S: 5, M: 10 });
    expect(r.amountsByVariation.S * 2).toBe(r.amountsByVariation.M);
  });

  it("hands out the whole total when it divides cleanly", () => {
    const r = suggestPerShareAmounts(100, 1, S_M(10, 5));
    // Σ count × amount = 10×5 + 5×10 = 100
    expect(r.actualTotal).toBe(100);
  });

  it("floors a fractional split to the tenth (mirror: {S:3.3, M:6.6})", () => {
    const r = suggestPerShareAmounts(100, 1, S_M(10, 10));
    expect(r.amountsByVariation).toEqual({ S: 3.3, M: 6.6 });
  });

  it("never over-allocates (floored total ≤ target)", () => {
    const r = suggestPerShareAmounts(100, 1, S_M(10, 10));
    expect(r.actualTotal).toBeLessThanOrEqual(100);
  });

  it("divides the total across the weeks (2 weeks halves per-share vs 1 week)", () => {
    const oneWeek = suggestPerShareAmounts(100, 1, S_M(10, 5));
    const twoWeeks = suggestPerShareAmounts(200, 2, S_M(10, 5));
    // 200 over 2 weeks == 100 per delivery == the one-week/100 case
    expect(twoWeeks.amountsByVariation).toEqual(oneWeek.amountsByVariation);
    expect(twoWeeks.actualTotal).toBe(200);
  });

  it("skips a size with missing average_weight", () => {
    const r = suggestPerShareAmounts(100, 1, [
      ...S_M(10, 5),
      { variationId: "NO_WEIGHT", averageWeight: null, subscriberCount: 3 },
    ]);
    expect(r.amountsByVariation).toEqual({ S: 5, M: 10 });
    expect("NO_WEIGHT" in r.amountsByVariation).toBe(false);
  });

  it("skips non-positive weights", () => {
    const r = suggestPerShareAmounts(100, 1, [
      { variationId: "S", averageWeight: 1, subscriberCount: 10 },
      { variationId: "ZERO", averageWeight: 0, subscriberCount: 5 },
      { variationId: "NEG", averageWeight: -2, subscriberCount: 5 },
    ]);
    expect(Object.keys(r.amountsByVariation)).toEqual(["S"]);
  });

  it("is not distributable with zero subscribers", () => {
    const r = suggestPerShareAmounts(100, 1, S_M(0, 0));
    expect(r.distributable).toBe(false);
    expect(r.amountsByVariation).toEqual({});
  });

  it("is not distributable with no target, zero or negative weeks", () => {
    expect(suggestPerShareAmounts(0, 1, S_M(10, 5)).distributable).toBe(false);
    expect(suggestPerShareAmounts(100, 0, S_M(10, 5)).distributable).toBe(false);
    expect(suggestPerShareAmounts(-5, 1, S_M(10, 5)).distributable).toBe(false);
  });

  it("floors to whole units for piece-based units (floorStep=1)", () => {
    // PCS: you can't deliver 0.3 of a lettuce — whole pieces only.
    const r = suggestPerShareAmounts(100, 1, S_M(10, 10), { floorStep: 1 });
    // per-weight unit = 100/30 = 3.33; S=floor(3.33)=3, M=floor(6.66)=6
    expect(r.amountsByVariation).toEqual({ S: 3, M: 6 });
  });

  it("avoids float-noise off-by-a-tenth (0.4, not a naive-floored 0.3)", () => {
    // total 2, count 5 → amount = 2/5 = 0.4 exactly, but 1.2 × (2/6) evaluates
    // to 0.39999999999999997 in float. Naive `Math.floor(v/0.1)*0.1` would give
    // 0.3; the toFixed-guarded floor must give 0.4.
    const r = suggestPerShareAmounts(2, 1, [
      { variationId: "X", averageWeight: 1.2, subscriberCount: 5 },
    ]);
    expect(r.amountsByVariation.X).toBe(0.4);
  });
});

describe("countDeliveryWeeks", () => {
  it("counts an inclusive range", () => {
    expect(countDeliveryWeeks(10, 12)).toBe(3); // 10, 11, 12
  });

  it("only odd weeks", () => {
    expect(countDeliveryWeeks(10, 15, { onlyOdd: true })).toBe(3); // 11,13,15
  });

  it("only even weeks", () => {
    expect(countDeliveryWeeks(10, 15, { onlyEven: true })).toBe(3); // 10,12,14
  });

  it("every third week from the start", () => {
    expect(countDeliveryWeeks(10, 20, { onlyEveryThree: true })).toBe(4); // 10,13,16,19
  });

  it("returns 0 for an inverted or invalid range", () => {
    expect(countDeliveryWeeks(20, 10)).toBe(0);
    expect(countDeliveryWeeks(null, 10)).toBe(0);
    expect(countDeliveryWeeks(10, undefined)).toBe(0);
  });
});
