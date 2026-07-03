import { describe, expect, it } from "vitest";

import { computeLineNetto, roundHalfUp } from "../lineNetto";

describe("computeLineNetto (BL-15: per-line ROUND_HALF_UP)", () => {
  it("quantizes a half-cent line up, matching the backend per-line rounding", () => {
    // 3 * 0.335 = 1.005 → 1.01 (half-up), not the raw 1.005. Summing two such
    // lines then yields 2.02 (round-each-then-sum, the backend order), not the
    // old sum-then-round 2.01.
    expect(computeLineNetto({ amount: 3, price_per_unit: 0.335 })).toBe(1.01);
  });

  it("leaves a whole-cent line unchanged", () => {
    expect(computeLineNetto({ amount: 2, price_per_unit: 1.5 })).toBe(3);
  });

  it("applies the rabatt before rounding", () => {
    // base 10.00, 10% rabatt → 9.00
    expect(computeLineNetto({ amount: 1, price_per_unit: 10, rabatt: 10 })).toBe(9);
  });
});

describe("roundHalfUp", () => {
  it("rounds halves away from zero", () => {
    expect(roundHalfUp(1.005)).toBe(1.01);
    expect(roundHalfUp(2.5, 0)).toBe(3);
  });

  it("returns 0 for non-finite input", () => {
    expect(roundHalfUp(Number.NaN)).toBe(0);
  });
});
