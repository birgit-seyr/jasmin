import { describe, expect, it } from "vitest";

import { toDayNumber } from "../weekdayNames";

describe("toDayNumber", () => {
  it("keeps Monday through Sunday", () => {
    expect(toDayNumber(0)).toBe(0);
    expect(toDayNumber(6)).toBe(6);
  });

  it("turns anything else into null", () => {
    expect(toDayNumber(null)).toBeNull();
    expect(toDayNumber(-1)).toBeNull();
    expect(toDayNumber(7)).toBeNull();
    expect(toDayNumber(1.5)).toBeNull();
  });
});
