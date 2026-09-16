/**
 * The year/week pair every week-scoped page seeds its selector from.
 *
 * The two travel to the API as one ISO coordinate, so the year has to be the
 * ISO week-year: across New Year the calendar year already belongs to the next
 * year while the week still belongs to the old one, and the backend refuses
 * week 53 of a 52-week ISO year.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const seededPair = async (instant: string) => {
  vi.setSystemTime(new Date(instant));
  vi.resetModules();
  // The registry was just reset, so re-register the dayjs plugins on the fresh
  // singleton the hook module is about to import.
  await import("@shared/utils/dayjsSetup");
  const { currentYear, currentWeek } = await import("../useYearWeekState");
  return { currentYear, currentWeek };
};

describe("useYearWeekState — the seeded year/week pair", () => {
  beforeEach(() => vi.useFakeTimers({ toFake: ["Date"] }));
  afterEach(() => vi.useRealTimers());

  it.each([
    // ISO 2026-W53 runs to Sunday 2027-01-03, and ISO 2027 has 52 weeks.
    ["2027-01-01T12:00:00Z", 2026, 53],
    ["2027-01-03T12:00:00Z", 2026, 53],
    // The next 53-week ISO year that spills into January.
    ["2033-01-01T12:00:00Z", 2032, 53],
    // Mid-year the two readings agree.
    ["2026-06-15T12:00:00Z", 2026, 25],
  ])("seeds %s as ISO %i-W%i", async (instant, year, week) => {
    await expect(seededPair(instant as string)).resolves.toEqual({
      currentYear: year,
      currentWeek: week,
    });
  });

  it("never seeds a week the seeded year does not have", async () => {
    for (const instant of [
      "2027-01-01T12:00:00Z",
      "2027-01-02T12:00:00Z",
      "2033-01-01T12:00:00Z",
      "2026-12-31T12:00:00Z",
    ]) {
      const { currentYear, currentWeek } = await seededPair(instant);
      const dayjs = (await import("dayjs")).default;
      // December 28 always sits in its ISO year's last week, so its week
      // number is how many that year has — the same rule the backend applies.
      const weeksInSeededYear = dayjs(`${currentYear}-12-28`).isoWeek();
      expect(currentWeek).toBeLessThanOrEqual(weeksInSeededYear);
    }
  });
});
