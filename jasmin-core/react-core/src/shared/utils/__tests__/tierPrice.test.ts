import { describe, expect, it } from "vitest";
import { hasTierPrice, pickTierPrice, pickTierPriceFromAmount } from "../tierPrice";
// The backend prices a customer's order line with a Python port of these
// pickers (``apps/commissioning/services/tier_price.py``), tested against this
// same table, so the two cannot drift apart.
import cases from "./tierPriceCases.json";

const PRICES = { price_1: "2.00", price_2: "1.80", price_3: "1.60" };

describe("pickTierPrice", () => {
  it.each(cases.pick_tier_price)("$case", (row) => {
    // A tier the office added but left empty is stored as null, which the
    // pickers' ``number[]`` doesn't show.
    const tiers = row.tiers as number[];
    expect(pickTierPrice(row.pu_count, row.prices, tiers)).toBe(
      Number(row.expected),
    );
  });

  it("reads prices typed with a decimal comma", () => {
    expect(pickTierPrice(1, { price_1: "2,40" })).toBe(2.4);
  });

  it("falls back to a lower tier when a higher one is typed empty", () => {
    expect(pickTierPrice(12, { ...PRICES, price_3: "" }, [1, 5, 10])).toBe(1.8);
  });
});

describe("pickTierPriceFromAmount", () => {
  it.each(cases.pick_tier_price_from_amount)("$case", (row) => {
    expect(
      pickTierPriceFromAmount(row.amount, row.amount_per_pu, row.prices, row.tiers),
    ).toBe(Number(row.expected));
  });

  it("reads an amount typed with a decimal comma", () => {
    expect(pickTierPriceFromAmount("5,5", "1", PRICES, [1, 5, 10])).toBe(1.8);
  });
});

describe("hasTierPrice", () => {
  it("is true when any tier holds a price", () => {
    expect(hasTierPrice({ price_2: "1.80" })).toBe(true);
  });

  it("is false for missing or zero prices", () => {
    expect(hasTierPrice({})).toBe(false);
    expect(hasTierPrice({ price_1: 0, price_2: null, price_3: "0.00" })).toBe(false);
  });
});
