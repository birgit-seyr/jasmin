import { describe, expect, it } from "vitest";

import {
  __csvInternalsForTests,
  buildCsvString,
  resolveCsvDialect,
} from "../csv";

const { formatCsvValue, escapeCsvValue } = __csvInternalsForTests;

describe("resolveCsvDialect", () => {
  it("returns the German preset by default", () => {
    expect(resolveCsvDialect()).toEqual({
      delimiter: ";",
      decimalSeparator: ",",
      dateFormat: "dd.mm.yyyy",
    });
  });

  it("returns the English preset for 'en'", () => {
    expect(resolveCsvDialect("en")).toEqual({
      delimiter: ",",
      decimalSeparator: ".",
      dateFormat: "yyyy-mm-dd",
    });
  });

  it("is case-insensitive", () => {
    expect(resolveCsvDialect("EN").delimiter).toBe(",");
  });

  it("falls back to German for unknown presets", () => {
    expect(resolveCsvDialect("klingon").delimiter).toBe(";");
  });
});

describe("formatCsvValue", () => {
  const de = resolveCsvDialect("de");
  const en = resolveCsvDialect("en");

  it("renders empty string for null and undefined", () => {
    expect(formatCsvValue(null, de)).toBe("");
    expect(formatCsvValue(undefined, de)).toBe("");
  });

  it("uses the German decimal separator", () => {
    expect(formatCsvValue(12.5, de)).toBe("12,5");
  });

  it("keeps the dot for the English dialect", () => {
    expect(formatCsvValue(12.5, en)).toBe("12.5");
  });

  it("formats Date as dd.mm.yyyy in DE", () => {
    expect(formatCsvValue(new Date("2024-03-07T12:00:00Z"), de)).toBe(
      "07.03.2024",
    );
  });

  it("formats Date as yyyy-mm-dd in EN", () => {
    expect(formatCsvValue(new Date("2024-03-07T12:00:00Z"), en)).toBe(
      "2024-03-07",
    );
  });

  it("integers stay as plain numbers (no decimal separator)", () => {
    expect(formatCsvValue(42, de)).toBe("42");
  });
});

describe("escapeCsvValue", () => {
  const de = resolveCsvDialect("de");
  const en = resolveCsvDialect("en");

  it("does not quote a plain value", () => {
    expect(escapeCsvValue("hello", de)).toBe("hello");
  });

  it("quotes when the delimiter is present", () => {
    expect(escapeCsvValue("a;b", de)).toBe('"a;b"');
    expect(escapeCsvValue("a,b", en)).toBe('"a,b"');
  });

  it("quotes and doubles embedded quotes", () => {
    expect(escapeCsvValue('she said "hi"', de)).toBe('"she said ""hi"""');
  });

  it("quotes when the value contains a newline", () => {
    expect(escapeCsvValue("line1\nline2", de)).toBe('"line1\nline2"');
  });

  it("does not quote a comma in DE dialect (delimiter is ;)", () => {
    expect(escapeCsvValue("a,b", de)).toBe("a,b");
  });
});

describe("buildCsvString", () => {
  it("builds a complete DE CSV with header normalisation and escaping", () => {
    const csv = buildCsvString(
      ["name", "amount\nincl. tax", "note"],
      [
        ["Alice", 12.5, "ok"],
        ["Bob", 0, "needs ; review"],
      ],
    );
    expect(csv).toBe(
      ["name;amount incl. tax;note", "Alice;12,5;ok", 'Bob;0;"needs ; review"'].join(
        "\n",
      ),
    );
  });

  it("uses comma + dot for the EN dialect", () => {
    const csv = buildCsvString(
      ["a", "b"],
      [["x", 1.5]],
      resolveCsvDialect("en"),
    );
    expect(csv).toBe("a,b\nx,1.5");
  });
});
