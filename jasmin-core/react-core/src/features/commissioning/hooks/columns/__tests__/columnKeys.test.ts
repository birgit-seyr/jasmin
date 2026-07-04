/**
 * Pins the EXACT wire format of the planning-grid column keys. These strings
 * cross to the Django backend verbatim, so a silent format change here would
 * break saving/reading planning amounts. The literal expectations below are the
 * contract — do not "adjust to match" a helper change; change the helper back.
 *
 * See docs/day-variation-columns-audit.md and columnKeys.ts.
 */
import { describe, expect, it } from "vitest";
import {
  dayAmountKey,
  dayHarvestedKey,
  dayPlannedAmountKey,
  dayVariationKey,
  dayVariationTier,
  isDayVariationKey,
  parseDayVariationKey,
  planningModeTier,
  variationAmountKey,
  variationColumnKey,
} from "../columnKeys";

// UUID-shaped ids, exactly as the backend emits them.
const DAY = "3f2504e0-4f89-11d3-9a0c-0305e82c3301";
const VAR = "9c858901-8a57-4791-81fe-4c455b099bc9";
const STATION = "b1e0a1c2-0000-4000-8000-000000000abc";

describe("dayVariationKey", () => {
  it("builds the bare (basic) leaf", () => {
    expect(dayVariationKey({ dayId: DAY, variationId: VAR })).toBe(
      `day_${DAY}_variation_${VAR}`,
    );
  });

  it("builds the tour leaf", () => {
    expect(dayVariationKey({ dayId: DAY, variationId: VAR, tour: 2 })).toBe(
      `day_${DAY}_variation_${VAR}_tour_2`,
    );
  });

  it("builds the station leaf", () => {
    expect(
      dayVariationKey({ dayId: DAY, variationId: VAR, station: STATION }),
    ).toBe(`day_${DAY}_variation_${VAR}_station_${STATION}`);
  });

  it("applies a prefix", () => {
    expect(
      dayVariationKey({ dayId: DAY, variationId: VAR, prefix: "backup_" }),
    ).toBe(`backup_day_${DAY}_variation_${VAR}`);
  });

  it("treats null/undefined tour & station as absent", () => {
    expect(
      dayVariationKey({
        dayId: DAY,
        variationId: VAR,
        tour: null,
        station: undefined,
      }),
    ).toBe(`day_${DAY}_variation_${VAR}`);
  });
});

describe("trailer + transposed + day-less keys", () => {
  it("dayPlannedAmountKey / dayHarvestedKey", () => {
    expect(dayPlannedAmountKey(DAY)).toBe(`day_${DAY}_planned_amount`);
    expect(dayHarvestedKey(DAY)).toBe(`day_${DAY}_harvested`);
  });

  it("dayAmountKey (AmountShares, no variation segment)", () => {
    expect(dayAmountKey({ dayId: DAY })).toBe(`amount_day_${DAY}`);
    expect(dayAmountKey({ dayId: DAY, tour: 3 })).toBe(`amount_day_${DAY}_tour_3`);
    expect(dayAmountKey({ dayId: DAY, station: STATION })).toBe(
      `amount_day_${DAY}_station_${STATION}`,
    );
  });

  it("variationColumnKey", () => {
    expect(variationColumnKey(VAR)).toBe(`variation_${VAR}`);
    expect(variationColumnKey(VAR, "backup_")).toBe(`backup_variation_${VAR}`);
  });

  it("variationAmountKey (long-term planner, distinct from dayAmountKey)", () => {
    expect(variationAmountKey(VAR)).toBe(`amount_${VAR}`);
    // Must NOT collide with the transposed AmountShares day key.
    expect(variationAmountKey(VAR)).not.toBe(dayAmountKey({ dayId: VAR }));
  });
});

describe("planningModeTier", () => {
  it("maps each mode to its tier (unknown → bare)", () => {
    expect(planningModeTier("basic")).toBe("bare");
    expect(planningModeTier("tours")).toBe("tour");
    expect(planningModeTier("stations")).toBe("station");
    expect(planningModeTier("something-else")).toBe("bare");
  });

  it("agrees with the tier a dayVariationKey built for that mode parses to", () => {
    expect(parseDayVariationKey(dayVariationKey({ dayId: DAY, variationId: VAR }))!.tier).toBe(
      planningModeTier("basic"),
    );
    expect(parseDayVariationKey(dayVariationKey({ dayId: DAY, variationId: VAR, tour: 1 }))!.tier).toBe(
      planningModeTier("tours"),
    );
    expect(parseDayVariationKey(dayVariationKey({ dayId: DAY, variationId: VAR, station: STATION }))!.tier).toBe(
      planningModeTier("stations"),
    );
  });
});

describe("parseDayVariationKey", () => {
  it("round-trips every tier and prefix", () => {
    for (const parts of [
      { dayId: DAY, variationId: VAR },
      { dayId: DAY, variationId: VAR, tour: 2 },
      { dayId: DAY, variationId: VAR, station: STATION },
      { dayId: DAY, variationId: VAR, prefix: "backup_" },
    ]) {
      const key = dayVariationKey(parts);
      const parsed = parseDayVariationKey(key);
      expect(parsed).not.toBeNull();
      expect(parsed!.dayId).toBe(DAY);
      expect(parsed!.variationId).toBe(VAR);
      expect(parsed!.prefix).toBe(parts.prefix ?? "");
      if (parts.tour !== undefined) expect(parsed!.tour).toBe(String(parts.tour));
      if (parts.station !== undefined) expect(parsed!.station).toBe(STATION);
    }
  });

  it("classifies the tier", () => {
    expect(parseDayVariationKey(dayVariationKey({ dayId: DAY, variationId: VAR }))!.tier).toBe("bare");
    expect(parseDayVariationKey(dayVariationKey({ dayId: DAY, variationId: VAR, tour: 1 }))!.tier).toBe("tour");
    expect(parseDayVariationKey(dayVariationKey({ dayId: DAY, variationId: VAR, station: STATION }))!.tier).toBe("station");
  });

  it("rejects non-variation keys (trailers, day-less, unrelated)", () => {
    expect(parseDayVariationKey(dayPlannedAmountKey(DAY))).toBeNull();
    expect(parseDayVariationKey(dayHarvestedKey(DAY))).toBeNull();
    expect(parseDayVariationKey(variationColumnKey(VAR))).toBeNull();
    expect(parseDayVariationKey("share_article")).toBeNull();
    expect(parseDayVariationKey("day_only_no_variation")).toBeNull();
  });
});

describe("predicates", () => {
  it("isDayVariationKey matches only variation cells", () => {
    expect(isDayVariationKey(dayVariationKey({ dayId: DAY, variationId: VAR }))).toBe(true);
    expect(isDayVariationKey(dayVariationKey({ dayId: DAY, variationId: VAR, prefix: "backup_" }))).toBe(true);
    expect(isDayVariationKey(dayPlannedAmountKey(DAY))).toBe(false);
    expect(isDayVariationKey("size")).toBe(false);
  });

  it("dayVariationTier returns null for non-variation keys", () => {
    expect(dayVariationTier(dayVariationKey({ dayId: DAY, variationId: VAR, tour: 1 }))).toBe("tour");
    expect(dayVariationTier(dayPlannedAmountKey(DAY))).toBeNull();
  });
});
