import { describe, expect, it } from "vitest";
import { currencyCodeToSymbol } from "../currency";

describe("currencyCodeToSymbol", () => {

  it("returns the input code when it isn't registered", () => {
    // ``useCurrency().currencySymbol`` did this historically — the
    // util keeps the same fallback so unregistered tenants render
    // the bare ISO code instead of a stray ``€``.
    expect(currencyCodeToSymbol("XYZ")).toBe("XYZ");
    expect(currencyCodeToSymbol("JPY")).toBe("JPY");
  });

  it("returns the EUR symbol for empty / nullish input", () => {
    expect(currencyCodeToSymbol("")).toBe("€");
    expect(currencyCodeToSymbol(null)).toBe("€");
    expect(currencyCodeToSymbol(undefined)).toBe("€");
  });

  it("maps the registered codes", () => {
    expect(currencyCodeToSymbol("EUR")).toBe("€");
    expect(currencyCodeToSymbol("USD")).toBe("$");
    expect(currencyCodeToSymbol("GBP")).toBe("£");
    expect(currencyCodeToSymbol("CHF")).toBe("CHF");
  });
});
