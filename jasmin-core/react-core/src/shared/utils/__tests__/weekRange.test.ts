import { afterEach, describe, expect, it, vi } from "vitest";

import {
  activeAtDateForWeek,
  dateForWeekDayNumber,
  hasWeekBegun,
  isWeekInPast,
  mondayOfIsoWeek,
  nextIsoWeek,
} from "../weekRange";

// The ISO weeks around New Year belong to the year they mostly lie in, not to
// the calendar date: 1–3 January 2027 are week 53 of 2026, 29–31 December 2025
// week 1 of 2026. The helpers must give the same dates on those days as on any
// other.
function at(isoDate: string) {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(`${isoDate}T12:00:00`));
}

afterEach(() => {
  vi.useRealTimers();
});

const day = (value: { format: (pattern: string) => string }) =>
  value.format("YYYY-MM-DD");

describe("mondayOfIsoWeek", () => {
  it("finds the Monday of an ISO week, also when it lies in the other calendar year", () => {
    expect(day(mondayOfIsoWeek(2026, 1))).toBe("2025-12-29");
    expect(day(mondayOfIsoWeek(2026, 53))).toBe("2026-12-28");
    expect(day(mondayOfIsoWeek(2027, 1))).toBe("2027-01-04");
    expect(day(mondayOfIsoWeek(2025, 10))).toBe("2025-03-03");
  });
});

describe("nextIsoWeek", () => {
  it.each([
    [2026, 41, 2026, 42],
    [2026, 52, 2026, 53],
    [2026, 53, 2027, 1],
    [2027, 52, 2028, 1],
  ])("follows %i week %i with %i week %i", (year, week, nextYear, nextWeek) => {
    expect(nextIsoWeek(year, week)).toEqual({ year: nextYear, week: nextWeek });
  });
});

describe("dateForWeekDayNumber", () => {
  it.each(["2027-01-01", "2026-12-31", "2026-10-06"])(
    "dates a delivery day the same on %s",
    (today) => {
      at(today);

      expect(day(dateForWeekDayNumber(2027, 5, 0))).toBe("2027-02-01");
      expect(day(dateForWeekDayNumber(2026, 53, 3))).toBe("2026-12-31");
      expect(day(dateForWeekDayNumber(2025, 10, 0))).toBe("2025-03-03");
      expect(day(dateForWeekDayNumber(2027, 1, 6))).toBe("2027-01-10");
    },
  );
});

describe("isWeekInPast", () => {
  it("keeps next week open on New Year's Day", () => {
    at("2027-01-01");

    expect(isWeekInPast(2027, 1)).toBe(false);
    expect(isWeekInPast(2026, 52)).toBe(false);
    expect(isWeekInPast(2026, 51)).toBe(true);
  });
});

describe("hasWeekBegun", () => {
  it("counts a week as begun from its Monday on", () => {
    at("2026-10-11"); // a Sunday, the last day of week 41

    expect(hasWeekBegun(2026, 41)).toBe(true);
    expect(hasWeekBegun(2026, 42)).toBe(false);

    at("2026-10-12"); // the Monday of week 42

    expect(hasWeekBegun(2026, 42)).toBe(true);
    expect(hasWeekBegun(2026, 43)).toBe(false);
  });

  it("finds the week across New Year", () => {
    at("2027-01-01"); // week 53 of 2026

    expect(hasWeekBegun(2026, 53)).toBe(true);
    expect(hasWeekBegun(2027, 1)).toBe(false);
  });

  it("does not count a missing week as begun", () => {
    expect(hasWeekBegun(2026, null)).toBe(false);
  });
});

describe("activeAtDateForWeek", () => {
  it("takes the week's Saturday on New Year's Day", () => {
    at("2027-01-01");

    expect(activeAtDateForWeek(2027, 1)).toBe("2027-01-09");
    expect(activeAtDateForWeek(2026, 53)).toBe("2027-01-02");
  });
});
