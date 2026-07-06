import dayjs from "dayjs";
import { describe, expect, it } from "vitest";
import { buildMonthlyIncomeSeries } from "../incomeSeries";

const SERIES = { id: "income", label: "Income", color: "#3f8600" };

describe("buildMonthlyIncomeSeries", () => {
  const range: [dayjs.Dayjs, dayjs.Dayjs] = [
    dayjs("2026-01-01"),
    dayjs("2026-03-31"),
  ];

  it("buckets amounts by month and zero-fills gaps across the range", () => {
    const { data, series } = buildMonthlyIncomeSeries(
      [
        { month: "2026-01", amount: "15.50" },
        { month: "2026-03", amount: "7.00" },
      ],
      range,
      SERIES,
    );
    // The 12-month floor means the window is wider than the 3-month range, but
    // the three range months carry the mapped/zero-filled values.
    const byLabel = new Map(data.map((d) => [d.label, d.income]));
    expect(byLabel.get("Jan '26")).toBe(15.5);
    expect(byLabel.get("Feb '26")).toBe(0); // no point → zero-filled
    expect(byLabel.get("Mar '26")).toBe(7);
    expect(series).toEqual([SERIES]);
  });

  it("spans at least 12 months even for a short range", () => {
    const { data } = buildMonthlyIncomeSeries([], range, SERIES);
    // end = 2026-03, minStart = 2026-03 - 11 = 2025-04 → 12 months inclusive.
    expect(data.length).toBe(12);
    expect(data[0].label).toBe("Apr '25");
    expect(data[data.length - 1].label).toBe("Mar '26");
    // Empty input → every month zero.
    expect(data.every((d) => d.income === 0)).toBe(true);
  });

  it("parses the money string, ignoring malformed amounts", () => {
    const { data } = buildMonthlyIncomeSeries(
      [
        { month: "2026-02", amount: "1234.56" },
        { month: "2026-01", amount: "not-a-number" },
      ],
      range,
      SERIES,
    );
    const byLabel = new Map(data.map((d) => [d.label, d.income]));
    expect(byLabel.get("Feb '26")).toBe(1234.56);
    expect(byLabel.get("Jan '26")).toBe(0); // NaN → 0
  });
});
