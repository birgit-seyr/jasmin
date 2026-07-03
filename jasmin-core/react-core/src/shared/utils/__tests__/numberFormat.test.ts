import { describe, expect, it } from "vitest";
import {
  formatNumber,
  getLocaleSeparators,
  parseLocaleNumber,
} from "../numberFormat";

describe("formatNumber", () => {
  it("formats integers with the locale's decimal + grouping", () => {
    expect(formatNumber(1234567.89, 2, "de-DE")).toBe("1.234.567,89");
    expect(formatNumber(1234567.89, 2, "en-US")).toBe("1,234,567.89");
    expect(formatNumber(1234567.89, 2, "fr-FR")).toMatch(/1.234.567,89/);
  });

  it("honors the requested decimal count exactly", () => {
    expect(formatNumber(7, 2, "de-DE")).toBe("7,00");
    expect(formatNumber(7.5, 0, "de-DE")).toBe("8"); // rounds
    expect(formatNumber(7.555, 2, "de-DE")).toBe("7,56");
  });

  it('returns "" for nullish / empty / NaN', () => {
    expect(formatNumber(null, 2, "de-DE")).toBe("");
    expect(formatNumber(undefined, 2, "de-DE")).toBe("");
    expect(formatNumber("", 2, "de-DE")).toBe("");
    expect(formatNumber("not a number", 2, "de-DE")).toBe("");
    expect(formatNumber(NaN, 2, "de-DE")).toBe("");
    expect(formatNumber(Infinity, 2, "de-DE")).toBe("");
  });

  it("accepts string numerics and Decimal-shaped strings", () => {
    // Backend sometimes returns Decimal as a string with canonical ".".
    expect(formatNumber("98.00", 2, "de-DE")).toBe("98,00");
    expect(formatNumber("98", 0, "de-DE")).toBe("98");
    expect(formatNumber("19.5", 2, "de-DE")).toBe("19,50");
  });

  it("handles negative values", () => {
    expect(formatNumber(-12.34, 2, "de-DE")).toBe("-12,34");
    expect(formatNumber(-12.34, 2, "en-US")).toBe("-12.34");
  });
});

describe("parseLocaleNumber", () => {
  it("interprets input via the locale's own separator conventions", () => {
    // In de-DE "." is the GROUPING char and "," is the decimal, so
    // "12.34" reads as twelve-thousand-three-hundred-and-forty — that's
    // the correct Intl semantics. We never feed canonical "." strings
    // into parse() in production; the form layer converts user input
    // ("12,34") to canonical "12.34" via getValueFromEvent.
    expect(parseLocaleNumber("12.34", "de-DE")).toBe(1234);
    // en-US: "." is decimal, no grouping change.
    expect(parseLocaleNumber("12.34", "en-US")).toBe(12.34);
  });

  it("parses locale-formatted input back to a JS number", () => {
    expect(parseLocaleNumber("12,34", "de-DE")).toBe(12.34);
    expect(parseLocaleNumber("1.234,56", "de-DE")).toBe(1234.56);
    expect(parseLocaleNumber("1,234.56", "en-US")).toBe(1234.56);
  });

  it("strips thousand grouping", () => {
    expect(parseLocaleNumber("1.234.567,89", "de-DE")).toBe(1234567.89);
    expect(parseLocaleNumber("1,234,567.89", "en-US")).toBe(1234567.89);
  });

  it("returns null for empty / invalid / non-numeric", () => {
    expect(parseLocaleNumber("", "de-DE")).toBeNull();
    expect(parseLocaleNumber(null, "de-DE")).toBeNull();
    expect(parseLocaleNumber(undefined, "de-DE")).toBeNull();
    expect(parseLocaleNumber("hello", "de-DE")).toBeNull();
  });

  it("passes JS numbers through unchanged", () => {
    expect(parseLocaleNumber(12.34, "de-DE")).toBe(12.34);
    expect(parseLocaleNumber(0, "de-DE")).toBe(0);
    expect(parseLocaleNumber(NaN, "de-DE")).toBeNull();
  });
});

describe("getLocaleSeparators", () => {
  it("derives correct separators for known locales", () => {
    expect(getLocaleSeparators("de-DE")).toEqual({
      decimalChar: ",",
      groupChar: ".",
    });
    expect(getLocaleSeparators("en-US")).toEqual({
      decimalChar: ".",
      groupChar: ",",
    });
  });
});

// ---------------------------------------------------------------------------
// Round-trip — what we ultimately rely on: a value can survive
// format -> parse -> format and stay identical (modulo precision).
// ---------------------------------------------------------------------------
describe("format / parse round-trip", () => {
  it.each([
    ["de-DE", 7, 0, "7"],
    ["de-DE", 7.5, 2, "7,50"],
    ["de-DE", 1234.56, 2, "1.234,56"],
    ["en-US", 1234.56, 2, "1,234.56"],
  ])(
    "%s: %f (%i decimals) round-trips through format/parse",
    (locale, value, decimals, expectedDisplay) => {
      const displayed = formatNumber(value, decimals, locale);
      expect(displayed).toBe(expectedDisplay);
      const parsedBack = parseLocaleNumber(displayed, locale);
      expect(parsedBack).toBe(Number(value.toFixed(decimals)));
    },
  );
});
