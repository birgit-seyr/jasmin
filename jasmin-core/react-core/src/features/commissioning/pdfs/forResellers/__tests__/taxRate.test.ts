/**
 * Tests for the front-end side of the tax_rate flow.
 *
 * Two surfaces are covered here:
 *
 *  1. `computeTaxBreakdown` — the canonical "group line items by VAT rate
 *     and produce a per-rate breakdown" helper that mirrors the backend
 *     `tax_breakdown` in apps/commissioning/models/mixin.py. Invoice
 *     totals on the PDF depend on this matching the backend exactly.
 *
 *  2. The "missing tax_rate falls through" behaviour — both backend and
 *     front-end treat a `null`/`undefined`/`0` line tax as 0 %. The two
 *     sides MUST agree, otherwise the PDF total drifts from the DB total.
 *
 * Notes on `||` vs `??`: the pre-fill defaults read from
 * `getSetting("default_tax_rate_*")` in modals + useOrdersData used to
 * use `|| 7`/`|| 19`, which silently overrides a legitimate `0 %` tenant
 * setting. Those are now `??`. These tests don't exercise the modals
 * directly (that needs full provider plumbing); they pin the
 * computeTaxBreakdown rounding and grouping behaviour the modals feed.
 */
import { describe, expect, it } from "vitest";
import {
  computeTaxBreakdown,
  type LineItemBase,
} from "../pdfBase";

const makeItem = (overrides: Partial<LineItemBase> = {}): LineItemBase => ({
  amount: 1,
  price_per_unit: 1,
  rabatt: 0,
  tax_rate: 7,
  ...overrides,
});

describe("computeTaxBreakdown — single rate", () => {
  it("buckets items by tax_rate and computes per-rate netto/tax/brutto", () => {
    const items = [
      makeItem({ amount: 2, price_per_unit: 5, tax_rate: 7 }),
      makeItem({ amount: 4, price_per_unit: 2.5, tax_rate: 7 }),
    ];

    const result = computeTaxBreakdown(items);

    // netto = 2*5 + 4*2.5 = 20.00
    // tax   = 20 * 7 / 100 = 1.40
    // brutto = 21.40
    expect(result).toEqual([
      { rate: 7, netto: 20, tax: 1.4, brutto: 21.4 },
    ]);
  });

  it("applies the rabatt discount before grouping", () => {
    const items = [
      // (amount * price_per_unit) * (1 - rabatt/100)
      makeItem({ amount: 10, price_per_unit: 1, rabatt: 10, tax_rate: 7 }),
    ];

    const result = computeTaxBreakdown(items);

    // netto = 10 * 1 * 0.9 = 9.00
    // tax   = 9 * 7 / 100 = 0.63
    expect(result).toEqual([{ rate: 7, netto: 9, tax: 0.63, brutto: 9.63 }]);
  });
});

describe("computeTaxBreakdown — multiple rates", () => {
  it("returns one bucket per distinct rate, sorted ascending", () => {
    const articles: LineItemBase[] = [
      makeItem({ amount: 1, price_per_unit: 100, tax_rate: 7 }),
    ];
    const crates: LineItemBase[] = [
      makeItem({ amount: 1, price_per_unit: 100, tax_rate: 19 }),
    ];

    const result = computeTaxBreakdown(articles, crates);

    // Order matters: 7 % first, 19 % second.
    expect(result.map((r) => r.rate)).toEqual([7, 19]);
    expect(result[0]).toEqual({ rate: 7, netto: 100, tax: 7, brutto: 107 });
    expect(result[1]).toEqual({ rate: 19, netto: 100, tax: 19, brutto: 119 });
  });

  it("rounds tax ONCE per rate (legal invoice rounding)", () => {
    // Sum nets first, then round-half-up; per-line tax rounding would
    // drift by a cent on long invoices. This is the key contract with
    // the backend's tax_breakdown helper (ROUND_HALF_UP per VAT rate).
    const items: LineItemBase[] = [
      makeItem({ amount: 1, price_per_unit: 3.33, tax_rate: 7 }),
      makeItem({ amount: 1, price_per_unit: 3.34, tax_rate: 7 }),
      makeItem({ amount: 1, price_per_unit: 3.33, tax_rate: 7 }),
    ];

    const result = computeTaxBreakdown(items);

    // netto = 10.00 (after rounding the sum once)
    // tax = 0.70
    expect(result[0].netto).toBe(10);
    expect(result[0].tax).toBe(0.7);
    expect(result[0].brutto).toBe(10.7);
  });
});

describe("computeTaxBreakdown — missing / falsy tax_rate", () => {
  it("treats undefined tax_rate as 0 %", () => {
    const items: LineItemBase[] = [
      makeItem({ amount: 1, price_per_unit: 50, tax_rate: undefined }),
    ];

    const result = computeTaxBreakdown(items);

    expect(result).toEqual([{ rate: 0, netto: 50, tax: 0, brutto: 50 }]);
  });

  it("treats 0 explicitly as 0 %", () => {
    // Important: `|| 0` and `?? 0` happen to behave the same for 0, but
    // ensuring the line lands in a 0 % bucket (not silently dropped) is
    // what keeps PDF totals consistent with the backend.
    const items: LineItemBase[] = [
      makeItem({ amount: 1, price_per_unit: 50, tax_rate: 0 }),
    ];

    const result = computeTaxBreakdown(items);

    expect(result).toEqual([{ rate: 0, netto: 50, tax: 0, brutto: 50 }]);
  });

  it("buckets 0 % and 7 % items separately even when summed together", () => {
    const items: LineItemBase[] = [
      makeItem({ amount: 1, price_per_unit: 100, tax_rate: 0 }),
      makeItem({ amount: 1, price_per_unit: 100, tax_rate: 7 }),
    ];

    const result = computeTaxBreakdown(items);

    expect(result).toEqual([
      { rate: 0, netto: 100, tax: 0, brutto: 100 },
      { rate: 7, netto: 100, tax: 7, brutto: 107 },
    ]);
  });
});

describe("computeTaxBreakdown — empty inputs", () => {
  it("returns [] for no items", () => {
    expect(computeTaxBreakdown()).toEqual([]);
    expect(computeTaxBreakdown([])).toEqual([]);
    expect(computeTaxBreakdown([], [])).toEqual([]);
  });
});

describe("tenant-default fallback semantics (regression for `||` → `??`)", () => {
  // These tests document the small util pattern used at every call site
  // that reads `default_tax_rate_*` from `getSetting`. The old `|| 7`
  // form silently overrode a legitimate 0 % setting; the new `?? 7` keeps
  // 0 if the tenant deliberately set it.
  const pickArticleDefault = (setting: unknown): number =>
    (setting as number) ?? 7;
  const pickCrateDefault = (setting: unknown): number =>
    (setting as number) ?? 19;

  it("returns the tenant setting when one is configured", () => {
    expect(pickArticleDefault(10)).toBe(10);
    expect(pickCrateDefault(16)).toBe(16);
  });

  it("preserves 0 instead of replacing it with the hardcoded default", () => {
    // The whole reason we moved off `||`. Tenants on reverse-charge /
    // charity rates may legitimately want 0.
    expect(pickArticleDefault(0)).toBe(0);
    expect(pickCrateDefault(0)).toBe(0);
  });

  it("falls back to the hardcoded default for null / undefined", () => {
    expect(pickArticleDefault(null)).toBe(7);
    expect(pickArticleDefault(undefined)).toBe(7);
    expect(pickCrateDefault(null)).toBe(19);
    expect(pickCrateDefault(undefined)).toBe(19);
  });
});
