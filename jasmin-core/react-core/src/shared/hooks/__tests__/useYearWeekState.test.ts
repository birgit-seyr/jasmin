/**
 * The year/week pair every week-scoped page seeds its selector from.
 *
 * The two travel to the API as one ISO coordinate, so the year has to be the
 * ISO week-year: across New Year the calendar year already belongs to the next
 * year while the week still belongs to the old one, and the backend refuses
 * week 53 of a 52-week ISO year.
 *
 * The clock is frozen on Tuesday 6 October 2026 (ISO week 41) before the
 * imports run, so every test that moves the clock before mounting shows that
 * the hook reads "today" when it mounts, not when its module loads.
 */
import { renderHook } from "@testing-library/react";
import dayjs from "dayjs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const LOADED_AT = vi.hoisted(() => {
  const loadedAt = new Date(2026, 9, 6, 12, 0);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(loadedAt);
  return loadedAt;
});

import {
  useYearWeekState,
  type UseYearWeekStateOptions,
} from "../useYearWeekState";

function mountOn(instant: string | Date, options?: UseYearWeekStateOptions) {
  vi.setSystemTime(new Date(instant));
  return renderHook(() => useYearWeekState(options)).result;
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(LOADED_AT);
});
afterEach(() => vi.useRealTimers());

describe("useYearWeekState — the seeded year/week pair", () => {
  it.each([
    // ISO 2026-W53 runs to Sunday 2027-01-03, and ISO 2027 has 52 weeks.
    ["2027-01-01T12:00:00Z", 2026, 53],
    ["2027-01-03T12:00:00Z", 2026, 53],
    // The first day of ISO 2027.
    ["2027-01-04T12:00:00Z", 2027, 1],
    // The next 53-week ISO year that spills into January.
    ["2033-01-01T12:00:00Z", 2032, 53],
    // Mid-year the two readings agree.
    ["2026-06-15T12:00:00Z", 2026, 25],
  ])("mounted on %s seeds ISO %i-W%i", (instant, year, week) => {
    const result = mountOn(instant);

    expect(result.current).toMatchObject({
      selectedYear: year,
      selectedWeek: week,
      currentYear: year,
      currentWeek: week,
    });
  });

  it("never seeds a week the seeded year does not have", () => {
    for (const instant of [
      "2027-01-01T12:00:00Z",
      "2027-01-02T12:00:00Z",
      "2033-01-01T12:00:00Z",
      "2026-12-31T12:00:00Z",
    ]) {
      const { selectedYear, selectedWeek } = mountOn(instant).current;
      // December 28 always sits in its ISO year's last week, so its week
      // number is how many that year has — the same rule the backend applies.
      const weeksInSeededYear = dayjs(`${selectedYear}-12-28`).isoWeek();
      expect(selectedWeek).toBeLessThanOrEqual(weeksInSeededYear);
    }
  });

  it("keeps the week it mounted on while the clock moves on", () => {
    vi.setSystemTime(new Date(2026, 11, 31, 23, 59));
    const { result, rerender } = renderHook(() => useYearWeekState());
    vi.setSystemTime(new Date(2027, 0, 4, 0, 1));
    rerender();

    expect(result.current).toMatchObject({
      selectedYear: 2026,
      selectedWeek: 53,
      currentYear: 2026,
      currentWeek: 53,
    });
  });

  it("starts the offset from the week it mounted on", () => {
    const result = mountOn(new Date(2026, 9, 13, 12, 0), { weekOffset: 1 });

    expect(result.current.selectedWeek).toBe(43);
    expect(result.current.currentWeek).toBe(42);
  });

  it("takes an explicit year and week over today", () => {
    const result = mountOn(new Date(2026, 9, 13, 12, 0), {
      initialYear: 2025,
      initialWeek: null,
    });

    expect(result.current).toMatchObject({
      selectedYear: 2025,
      selectedWeek: null,
      currentYear: 2026,
      currentWeek: 42,
    });
  });
});
