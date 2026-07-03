import dayjs from "dayjs";
import { describe, expect, it } from "vitest";
import { toValidDayjs } from "../dayjsParse";

/**
 * Regression guard for the intermittent production crash where AntD's
 * DatePicker received a *truthy but invalid* dayjs and blew up inside
 * rc-picker with "can't access property 'date', <x> is null".
 *
 * The contract: anything that doesn't parse to a valid date must become
 * ``null`` (picker falls back to today) — never a truthy Invalid Date.
 */
describe("toValidDayjs", () => {
  const DATE_FORMATS = ["DD.MM.YYYY", "YYYY-MM-DD"];

  it("returns null for empty-ish values", () => {
    expect(toValidDayjs(null, DATE_FORMATS)).toBeNull();
    expect(toValidDayjs(undefined, DATE_FORMATS)).toBeNull();
    expect(toValidDayjs("", DATE_FORMATS)).toBeNull();
  });

  it.each([
    "None", // a Python None leaking through the wire
    "null",
    " ",
    "2026", // partial date
    "Invalid date",
    "not-a-date",
  ])("returns null for the unparseable value %j (never a truthy Invalid Date)", (bad) => {
    const result = toValidDayjs(bad, DATE_FORMATS);
    // The whole point: it must be null, NOT a truthy invalid dayjs.
    expect(result).toBeNull();
  });

  it("parses a value matching the tenant date_format", () => {
    const result = toValidDayjs("05.01.2026", DATE_FORMATS);
    expect(result).not.toBeNull();
    expect(dayjs.isDayjs(result)).toBe(true);
    expect(result!.isValid()).toBe(true);
    expect(result!.format("YYYY-MM-DD")).toBe("2026-01-05");
  });

  it("parses an ISO value via the fallback format", () => {
    const result = toValidDayjs("2026-01-05", DATE_FORMATS);
    expect(result).not.toBeNull();
    expect(result!.format("YYYY-MM-DD")).toBe("2026-01-05");
  });

  it("parses time values with the time formats", () => {
    expect(toValidDayjs("14:30:00", ["HH:mm:ss", "HH:mm"])!.format("HH:mm")).toBe(
      "14:30",
    );
    expect(toValidDayjs("14:30", ["HH:mm:ss", "HH:mm"])!.format("HH:mm")).toBe(
      "14:30",
    );
    expect(toValidDayjs("not-a-time", ["HH:mm:ss", "HH:mm"])).toBeNull();
  });
});
