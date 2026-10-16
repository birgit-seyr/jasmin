import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { todayApiDate } from "../apiDate";

describe("todayApiDate", () => {
  beforeEach(() => {
    vi.stubEnv("TZ", "Europe/Berlin");
    vi.useFakeTimers({ toFake: ["Date"] });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllEnvs();
  });

  it("is the local date, which right after midnight is a day ahead of UTC", () => {
    // 00:30 in Berlin on 16 October is still 15 October in UTC.
    vi.setSystemTime(new Date("2026-10-15T22:30:00Z"));

    expect(todayApiDate()).toBe("2026-10-16");
  });
});
