import dayjs from "dayjs";
import customParseFormat from "dayjs/plugin/customParseFormat";
import { describe, expect, it } from "vitest";
import { computeValidUntil, parseDateLoose, weeksPerDelivery } from "../endOfTerm";

dayjs.extend(customParseFormat);

// Hand-picked 2026 Mondays + Sundays so the tests don't depend on
// today's date. 2026-01-05 is the first Monday of 2026.
const MON = (date: string) => {
  const d = dayjs(date, "YYYY-MM-DD", true);
  if (d.isoWeekday() !== 1) {
    throw new Error(`fixture ${date} is not a Monday`);
  }
  return d;
};

describe("computeValidUntil", () => {
  describe("subscriptionsEndAtEndOfSeason", () => {
    const settings = {
      subscriptionsEndAtEndOfSeason: true,
      subscriptionsEndAfterOneYear: false,
      seasonStartWeek: 14,
    };

    it("returns Sunday of (seasonWeek - 1) in next year when validFrom is AFTER seasonWeek", () => {
      // 2026-05-04 = Monday of ISO W19 (> seasonWeek 14)
      const result = computeValidUntil(MON("2026-05-04"), settings);
      // Monday of W14 in 2027 is 2027-04-05, -1 day = 2027-04-04 (Sunday).
      expect(result?.format("YYYY-MM-DD")).toBe("2027-04-04");
      expect(result?.isoWeekday()).toBe(7);
    });

    it("returns Sunday OF seasonWeek in same year when validFrom is BEFORE seasonWeek", () => {
      // 2026-02-09 = Monday of ISO W7 (< seasonWeek 14)
      const result = computeValidUntil(MON("2026-02-09"), settings);
      // Sunday of W14 in 2026 is 2026-04-05.
      expect(result?.format("YYYY-MM-DD")).toBe("2026-04-05");
      expect(result?.isoWeekday()).toBe(7);
    });

    it("treats validFromWeek === seasonWeek as the new-season branch", () => {
      // 2026-03-30 = Monday of W14 (boundary case)
      const result = computeValidUntil(MON("2026-03-30"), settings);
      // Same as above: Monday of W14 in 2027 - 1 day.
      expect(result?.format("YYYY-MM-DD")).toBe("2027-04-04");
    });

    it("returns null when seasonStartWeek is missing", () => {
      const result = computeValidUntil(MON("2026-05-04"), {
        ...settings,
        seasonStartWeek: null,
      });
      expect(result).toBeNull();
    });

    it("returns null when seasonStartWeek is out of range", () => {
      const result = computeValidUntil(MON("2026-05-04"), {
        ...settings,
        seasonStartWeek: 0,
      });
      expect(result).toBeNull();
    });

    it("accepts string season-week values (defensive against orval drift)", () => {
      // Belt-and-braces: even if the API client returns a string,
      // the formula treats it as a number.
      const result = computeValidUntil(MON("2026-05-04"), {
        ...settings,
        seasonStartWeek: "14" as unknown as number,
      });
      expect(result?.format("YYYY-MM-DD")).toBe("2027-04-04");
    });
  });

  describe("subscriptionsEndAfterOneYear", () => {
    const settings = {
      subscriptionsEndAtEndOfSeason: false,
      subscriptionsEndAfterOneYear: true,
      seasonStartWeek: null,
    };

    it("returns validFrom + 52 weeks - 1 day (Sunday)", () => {
      // 2026-04-06 (Monday) + 52 weeks = 2027-04-05 (Monday).
      // -1 day = 2027-04-04 (Sunday).
      const result = computeValidUntil(MON("2026-04-06"), settings);
      expect(result?.format("YYYY-MM-DD")).toBe("2027-04-04");
      expect(result?.isoWeekday()).toBe(7);
    });

    it("works correctly across year boundaries", () => {
      // 2026-12-28 (Monday) + 52 weeks = 2027-12-27 (Monday).
      // -1 day = 2027-12-26 (Sunday).
      const result = computeValidUntil(MON("2026-12-28"), settings);
      expect(result?.format("YYYY-MM-DD")).toBe("2027-12-26");
      expect(result?.isoWeekday()).toBe(7);
    });
  });

  describe("trial branch (allowed_trial_subscription_duration)", () => {
    it("returns validFrom + N weeks - 1 day (Sunday) for an N-delivery trial", () => {
      // 2026-04-06 (Monday) + 4 weeks = 2026-05-04 (Monday).
      // -1 day = 2026-05-03 (Sunday).
      const result = computeValidUntil(MON("2026-04-06"), {
        subscriptionsEndAtEndOfSeason: false,
        subscriptionsEndAfterOneYear: false,
        seasonStartWeek: null,
        isTrial: true,
        trialDurationInDeliveries: 4,
      });
      expect(result?.format("YYYY-MM-DD")).toBe("2026-05-03");
      expect(result?.isoWeekday()).toBe(7);
    });

    it("trial wins over season-end-of-year when both would apply", () => {
      // Without ``isTrial`` this same input lands on 2027-04-04
      // (season branch). With the trial flag on it must collapse to
      // the short window.
      const result = computeValidUntil(MON("2026-05-04"), {
        subscriptionsEndAtEndOfSeason: true,
        subscriptionsEndAfterOneYear: false,
        seasonStartWeek: 14,
        isTrial: true,
        trialDurationInDeliveries: 4,
      });
      // 2026-05-04 + 4 weeks = 2026-06-01 (Monday). -1 day = 2026-05-31.
      expect(result?.format("YYYY-MM-DD")).toBe("2026-05-31");
    });

    it("trial wins over end-after-one-year when both would apply", () => {
      const result = computeValidUntil(MON("2026-04-06"), {
        subscriptionsEndAtEndOfSeason: false,
        subscriptionsEndAfterOneYear: true,
        seasonStartWeek: null,
        isTrial: true,
        trialDurationInDeliveries: 2,
      });
      // 2026-04-06 + 2 weeks = 2026-04-20 (Monday). -1 day = 2026-04-19.
      expect(result?.format("YYYY-MM-DD")).toBe("2026-04-19");
    });

    it("returns null when isTrial=true but duration is missing", () => {
      // Office-side: no setting configured → don't guess a default,
      // let the office type the end date.
      const result = computeValidUntil(MON("2026-04-06"), {
        subscriptionsEndAtEndOfSeason: false,
        subscriptionsEndAfterOneYear: true,
        seasonStartWeek: null,
        isTrial: true,
        trialDurationInDeliveries: null,
      });
      expect(result).toBeNull();
    });

    it("returns null when isTrial=true but duration is zero or negative", () => {
      const zero = computeValidUntil(MON("2026-04-06"), {
        subscriptionsEndAtEndOfSeason: false,
        subscriptionsEndAfterOneYear: true,
        seasonStartWeek: null,
        isTrial: true,
        trialDurationInDeliveries: 0,
      });
      expect(zero).toBeNull();

      const negative = computeValidUntil(MON("2026-04-06"), {
        subscriptionsEndAtEndOfSeason: false,
        subscriptionsEndAfterOneYear: true,
        seasonStartWeek: null,
        isTrial: true,
        trialDurationInDeliveries: -1,
      });
      expect(negative).toBeNull();
    });

    it("spans 2 weeks per delivery for an ODD_WEEKS variation", () => {
      // 4 deliveries × 2 weeks = 8 weeks.
      // 2026-04-06 (Monday) + 8 weeks = 2026-06-01 (Monday).
      // -1 day = 2026-05-31 (Sunday).
      const result = computeValidUntil(MON("2026-04-06"), {
        subscriptionsEndAtEndOfSeason: false,
        subscriptionsEndAfterOneYear: false,
        seasonStartWeek: null,
        isTrial: true,
        trialDurationInDeliveries: 4,
        trialWeeksPerDelivery: weeksPerDelivery("ODD_WEEKS"),
      });
      expect(result?.format("YYYY-MM-DD")).toBe("2026-05-31");
      expect(result?.isoWeekday()).toBe(7);
    });

    it("spans 4 weeks per delivery for an ALL_FOUR_WEEKS variation", () => {
      // 3 deliveries × 4 weeks = 12 weeks.
      // 2026-04-06 + 12 weeks = 2026-06-29 (Monday). -1 day = 2026-06-28.
      const result = computeValidUntil(MON("2026-04-06"), {
        subscriptionsEndAtEndOfSeason: false,
        subscriptionsEndAfterOneYear: false,
        seasonStartWeek: null,
        isTrial: true,
        trialDurationInDeliveries: 3,
        trialWeeksPerDelivery: weeksPerDelivery("ALL_FOUR_WEEKS"),
      });
      expect(result?.format("YYYY-MM-DD")).toBe("2026-06-28");
      expect(result?.isoWeekday()).toBe(7);
    });

    it("defaults to 1 week per delivery when weeksPerDelivery is missing", () => {
      // No ``trialWeeksPerDelivery`` → WEEKLY behaviour (1).
      const result = computeValidUntil(MON("2026-04-06"), {
        subscriptionsEndAtEndOfSeason: false,
        subscriptionsEndAfterOneYear: false,
        seasonStartWeek: null,
        isTrial: true,
        trialDurationInDeliveries: 4,
      });
      // 4 weeks → 2026-05-03 (Sunday).
      expect(result?.format("YYYY-MM-DD")).toBe("2026-05-03");
    });

    it("guards against an invalid weeksPerDelivery (falls back to 1)", () => {
      const result = computeValidUntil(MON("2026-04-06"), {
        subscriptionsEndAtEndOfSeason: false,
        subscriptionsEndAfterOneYear: false,
        seasonStartWeek: null,
        isTrial: true,
        trialDurationInDeliveries: 4,
        trialWeeksPerDelivery: 0,
      });
      // 4 × 1 weeks = 4 weeks → 2026-05-03.
      expect(result?.format("YYYY-MM-DD")).toBe("2026-05-03");
    });

    it("ignores the trial flag when it is false (falls through to season/year branch)", () => {
      const result = computeValidUntil(MON("2026-04-06"), {
        subscriptionsEndAtEndOfSeason: false,
        subscriptionsEndAfterOneYear: true,
        seasonStartWeek: null,
        isTrial: false,
        trialDurationInDeliveries: 4,
      });
      // Year branch: 2026-04-06 + 52 weeks - 1 day = 2027-04-04.
      expect(result?.format("YYYY-MM-DD")).toBe("2027-04-04");
    });
  });

  describe("priority + null fallback", () => {
    it("end-of-season takes precedence over end-after-year when both are on", () => {
      const result = computeValidUntil(MON("2026-05-04"), {
        subscriptionsEndAtEndOfSeason: true,
        subscriptionsEndAfterOneYear: true,
        seasonStartWeek: 14,
      });
      // season-rule answer; the one-year answer would also be
      // 2027-04-04 in this case (coincidence) — to be sure the
      // season branch is the one firing, use a different valid_from
      // where the two formulas diverge.
      expect(result?.format("YYYY-MM-DD")).toBe("2027-04-04");

      // Diverging example: validFromWeek < seasonWeek → season
      // branch returns same-year Sunday; one-year branch returns
      // a +52w Sunday.
      const divergent = computeValidUntil(MON("2026-02-09"), {
        subscriptionsEndAtEndOfSeason: true,
        subscriptionsEndAfterOneYear: true,
        seasonStartWeek: 14,
      });
      expect(divergent?.format("YYYY-MM-DD")).toBe("2026-04-05");
    });

    it("returns null when neither rule is active", () => {
      const result = computeValidUntil(MON("2026-04-06"), {
        subscriptionsEndAtEndOfSeason: false,
        subscriptionsEndAfterOneYear: false,
        seasonStartWeek: null,
      });
      expect(result).toBeNull();
    });

    it("returns null for an invalid validFrom", () => {
      const result = computeValidUntil(dayjs("not-a-date"), {
        subscriptionsEndAtEndOfSeason: false,
        subscriptionsEndAfterOneYear: true,
        seasonStartWeek: null,
      });
      expect(result).toBeNull();
    });
  });
});

describe("computeValidUntil — Sunday invariant", () => {
  // TimeBoundMixin requires valid_until to be a Sunday (isoWeekday=7).
  // Every code path that returns a non-null Dayjs must satisfy that.
  // This block exercises the full cycle × N matrix on the trial
  // branch plus the season + year branches, and asserts the weekday
  // on every result.

  const MONDAYS_2026 = [
    "2026-01-05",
    "2026-04-06",
    "2026-07-06",
    "2026-12-28", // year-boundary case
  ];

  const TRIAL_N_VALUES = [1, 2, 4, 12, 26];
  const CYCLES = [
    "WEEKLY",
    "ODD_WEEKS",
    "EVEN_WEEKS",
    "ALL_THREE_WEEKS",
    "ALL_FOUR_WEEKS",
  ] as const;

  it.each(MONDAYS_2026)(
    "trial branch lands on Sunday for every (cycle, N) starting %s",
    (mondayIso) => {
      for (const cycle of CYCLES) {
        for (const n of TRIAL_N_VALUES) {
          const result = computeValidUntil(MON(mondayIso), {
            subscriptionsEndAtEndOfSeason: false,
            subscriptionsEndAfterOneYear: false,
            seasonStartWeek: null,
            isTrial: true,
            trialDurationInDeliveries: n,
            trialWeeksPerDelivery: weeksPerDelivery(cycle),
          });
          expect(
            result?.isoWeekday(),
            `trial: validFrom=${mondayIso} cycle=${cycle} N=${n} → ${result?.format("YYYY-MM-DD")}`,
          ).toBe(7);
        }
      }
    },
  );

  it.each(MONDAYS_2026)(
    "trial branch tolerates fractional N and still lands on Sunday (%s)",
    (mondayIso) => {
      // Defence-in-depth: corrupted JSON could in principle send a
      // non-integer N. The implementation floors it, so the result
      // still preserves the weekday.
      const result = computeValidUntil(MON(mondayIso), {
        subscriptionsEndAtEndOfSeason: false,
        subscriptionsEndAfterOneYear: false,
        seasonStartWeek: null,
        isTrial: true,
        trialDurationInDeliveries: 4.7 as unknown as number,
        trialWeeksPerDelivery: weeksPerDelivery("ALL_FOUR_WEEKS"),
      });
      expect(result?.isoWeekday()).toBe(7);
    },
  );

  it.each(MONDAYS_2026)(
    "year branch lands on Sunday starting %s",
    (mondayIso) => {
      const result = computeValidUntil(MON(mondayIso), {
        subscriptionsEndAtEndOfSeason: false,
        subscriptionsEndAfterOneYear: true,
        seasonStartWeek: null,
      });
      expect(result?.isoWeekday()).toBe(7);
    },
  );

  it.each(MONDAYS_2026)(
    "season branch lands on Sunday starting %s (seasonStartWeek=14)",
    (mondayIso) => {
      const result = computeValidUntil(MON(mondayIso), {
        subscriptionsEndAtEndOfSeason: true,
        subscriptionsEndAfterOneYear: false,
        seasonStartWeek: 14,
      });
      expect(result?.isoWeekday()).toBe(7);
    },
  );
});

describe("weeksPerDelivery", () => {
  it.each([
    ["WEEKLY", 1],
    ["ODD_WEEKS", 2],
    ["EVEN_WEEKS", 2],
    ["ALL_THREE_WEEKS", 3],
    ["ALL_FOUR_WEEKS", 4],
  ] as const)("maps %s → %d weeks per delivery", (cycle, expected) => {
    expect(weeksPerDelivery(cycle)).toBe(expected);
  });

  it.each([null, undefined, "", "BOGUS"])(
    "falls back to WEEKLY (1) for invalid / missing cycle %p",
    (cycle) => {
      expect(weeksPerDelivery(cycle as string | null | undefined)).toBe(1);
    },
  );
});

describe("parseDateLoose", () => {
  it("returns null for falsy values", () => {
    expect(parseDateLoose(undefined, "DD.MM.YYYY")).toBeNull();
    expect(parseDateLoose(null, "DD.MM.YYYY")).toBeNull();
    expect(parseDateLoose("", "DD.MM.YYYY")).toBeNull();
  });

  it("parses the display format", () => {
    const parsed = parseDateLoose("06.04.2026", "DD.MM.YYYY");
    expect(parsed?.format("YYYY-MM-DD")).toBe("2026-04-06");
  });

  it("falls back to ISO 8601 when display format fails", () => {
    const parsed = parseDateLoose("2026-04-06", "DD.MM.YYYY");
    expect(parsed?.format("YYYY-MM-DD")).toBe("2026-04-06");
  });

  it("passes through a valid Dayjs instance", () => {
    const input = dayjs("2026-04-06", "YYYY-MM-DD", true);
    const parsed = parseDateLoose(input, "DD.MM.YYYY");
    expect(parsed?.isSame(input)).toBe(true);
  });

  it("returns null on unparseable strings", () => {
    expect(parseDateLoose("not-a-date", "DD.MM.YYYY")).toBeNull();
  });
});
