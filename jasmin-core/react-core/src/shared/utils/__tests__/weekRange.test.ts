import dayjs from "dayjs";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  activeAtDateForWeek,
  dateForWeekDayNumber,
  formatWeekKey,
  hasWeekBegun,
  isDayInPast,
  isWeekInPast,
  mondayOfIsoWeek,
  nextIsoWeek,
  previousIsoWeek,
  termWeekKeys,
  weeksInIsoYear,
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

describe("previousIsoWeek", () => {
  it.each([
    [2026, 42, 2026, 41],
    [2027, 1, 2026, 53],
    [2026, 1, 2025, 52],
  ])("precedes %i week %i with %i week %i", (year, week, lastYear, lastWeek) => {
    expect(previousIsoWeek(year, week)).toEqual({ year: lastYear, week: lastWeek });
  });
});

describe("weeksInIsoYear", () => {
  it.each([
    [2025, 52],
    [2026, 53],
    [2027, 52],
    [2020, 53],
  ])("%i has %i ISO weeks", (year, weeks) => {
    expect(weeksInIsoYear(year)).toBe(weeks);
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

describe("isDayInPast", () => {
  it("counts the days before today as past, and not today", () => {
    at("2026-11-12"); // the Thursday of week 46

    expect(isDayInPast(2026, 46, 2)).toBe(true);
    expect(isDayInPast(2026, 46, 3)).toBe(false);
    expect(isDayInPast(2026, 46, 4)).toBe(false);
    expect(isDayInPast(2026, 45, 6)).toBe(true);
  });

  it("finds the day across New Year", () => {
    at("2027-01-01"); // the Friday of week 53 of 2026

    expect(isDayInPast(2026, 53, 3)).toBe(true);
    expect(isDayInPast(2026, 53, 4)).toBe(false);
    expect(isDayInPast(2027, 1, 0)).toBe(false);
  });

  it("does not count a missing day as past", () => {
    at("2026-11-12");

    expect(isDayInPast(2026, 46, null)).toBe(false);
    expect(isDayInPast(2026, null, 0)).toBe(false);
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

describe("termWeekKeys", () => {
  it("keys every ISO week a range touches, across New Year", () => {
    // A Wednesday start counts its whole week.
    expect(termWeekKeys(dayjs("2025-12-24"), dayjs("2026-01-11"))).toEqual([
      "2025-52",
      "2026-1",
      "2026-2",
    ]);
  });
});

describe("formatWeekKey", () => {
  it("reads a week key as week/year", () => {
    expect(formatWeekKey("2026-30")).toBe("30/2026");
  });
});
