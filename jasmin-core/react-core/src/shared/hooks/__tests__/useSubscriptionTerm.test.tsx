/**
 * ``useSubscriptionTerm`` start-date rule: Mondays on or after the tenant's
 * lead time, or any Monday (past ones too) with the office-only
 * ``allowPastStart`` option used while the tenant is in onboarding mode.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import dayjs from "dayjs";

vi.mock("../configuration/useTenant", () => ({
  useTenant: () => ({
    tenant: null,
    getSetting: (key: string, defaultValue: unknown = null) =>
      key === "min_weeks_from_creation_to_start_delivery" ? 2 : defaultValue,
  }),
}));

import { useSubscriptionTerm } from "../useSubscriptionTerm";

// "Today" is Wednesday 2026-07-22; two weeks of lead time make Monday
// 2026-08-10 the earliest start.
const TODAY = new Date(2026, 6, 22, 10, 0);
const EARLIEST_START = "2026-08-10";
const PAST_MONDAY = "2026-06-01";
const MONDAY_INSIDE_LEAD_TIME = "2026-08-03";
const PAST_TUESDAY = "2026-06-02";
const FUTURE_TUESDAY = "2026-08-11";

describe("useSubscriptionTerm valid_from rule", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(TODAY);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps the lead time by default", () => {
    const { result } = renderHook(() => useSubscriptionTerm());
    const { disabledValidFromDate, earliestValidFrom } = result.current;

    expect(earliestValidFrom.format("YYYY-MM-DD")).toBe(EARLIEST_START);
    expect(disabledValidFromDate(dayjs(PAST_MONDAY))).toBe(true);
    expect(disabledValidFromDate(dayjs(MONDAY_INSIDE_LEAD_TIME))).toBe(true);
    expect(disabledValidFromDate(dayjs(EARLIEST_START))).toBe(false);
    expect(disabledValidFromDate(dayjs(FUTURE_TUESDAY))).toBe(true);
  });

  it("allows any Monday with allowPastStart", () => {
    const { result } = renderHook(() =>
      useSubscriptionTerm({ allowPastStart: true }),
    );
    const { disabledValidFromDate, earliestValidFrom } = result.current;

    expect(disabledValidFromDate(dayjs(PAST_MONDAY))).toBe(false);
    expect(disabledValidFromDate(dayjs(MONDAY_INSIDE_LEAD_TIME))).toBe(false);
    expect(disabledValidFromDate(dayjs(EARLIEST_START))).toBe(false);
    // The Monday rule stays, and the earliest sellable start is unchanged.
    expect(disabledValidFromDate(dayjs(PAST_TUESDAY))).toBe(true);
    expect(disabledValidFromDate(dayjs(FUTURE_TUESDAY))).toBe(true);
    expect(earliestValidFrom.format("YYYY-MM-DD")).toBe(EARLIEST_START);
  });

  it("does not disable an empty picker value", () => {
    const { result } = renderHook(() =>
      useSubscriptionTerm({ allowPastStart: true }),
    );
    expect(result.current.disabledValidFromDate(null)).toBe(false);
  });
});
