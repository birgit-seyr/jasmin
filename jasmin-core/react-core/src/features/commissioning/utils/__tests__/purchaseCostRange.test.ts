import dayjs from "dayjs";
import { describe, expect, it } from "vitest";

import {
  MAX_PURCHASE_COST_RANGE_YEARS,
  isOutsidePurchaseCostRange,
} from "../purchaseCostRange";

// The server's cap, in days: apps/commissioning/views/statistic_views.py
// (_MAX_PURCHASE_COST_SPAN_YEARS * 366).
const SERVER_CAP_DAYS = MAX_PURCHASE_COST_RANGE_YEARS * 366;

const start = dayjs("2021-01-04");
const end = dayjs("2026-01-04");

describe("isOutsidePurchaseCostRange", () => {
  it("disables nothing while the panel has no bound yet", () => {
    expect(isOutsidePurchaseCostRange(dayjs("1990-01-01"), null)).toBe(false);
    expect(isOutsidePurchaseCostRange(dayjs("2099-01-01"), undefined)).toBe(
      false,
    );
    expect(isOutsidePurchaseCostRange(dayjs("2099-01-01"), [null, null])).toBe(
      false,
    );
  });

  it("keeps the full span selectable from a picked start", () => {
    const last = start.add(MAX_PURCHASE_COST_RANGE_YEARS, "year");
    expect(isOutsidePurchaseCostRange(last, [start, null])).toBe(false);
    expect(isOutsidePurchaseCostRange(last.add(1, "day"), [start, null])).toBe(
      true,
    );
  });

  it("keeps the full span selectable back from a picked end", () => {
    const first = end.subtract(MAX_PURCHASE_COST_RANGE_YEARS, "year");
    expect(isOutsidePurchaseCostRange(first, [null, end])).toBe(false);
    expect(
      isOutsidePurchaseCostRange(first.subtract(1, "day"), [null, end]),
    ).toBe(true);
  });

  it("never allows a span the server would refuse", () => {
    const widest = start.add(MAX_PURCHASE_COST_RANGE_YEARS, "year");
    expect(widest.diff(start, "day")).toBeLessThanOrEqual(SERVER_CAP_DAYS);
  });

  it("refuses the decade-wide range the report used to be asked for", () => {
    expect(isOutsidePurchaseCostRange(dayjs("2015-01-01"), [null, end])).toBe(
      true,
    );
  });
});
