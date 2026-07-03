import dayjs from "dayjs";
import { describe, expect, it } from "vitest";
// Importing the module is enough — it extends the dayjs singleton on load.
// (The vitest setup imports it too, mirroring the app's main.tsx boot.)
import "../dayjsSetup";

/**
 * Guards the systemic fix: every dayjs plugin the app depends on must be
 * registered on the singleton at boot, so no lazily-loaded chunk can render
 * a date widget before its plugin exists. Dropping a plugin from
 * ``dayjsSetup.ts`` breaks the feature that relied on the old scattered
 * ``dayjs.extend`` — this test turns that into a red build.
 */
describe("dayjsSetup — boot-time dayjs plugins", () => {
  it("registers isoWeek (isoWeekday/isoWeek)", () => {
    expect(typeof dayjs().isoWeekday).toBe("function");
    expect(typeof dayjs().isoWeek).toBe("function");
    // Monday 2026-01-05 → isoWeekday 1.
    expect(dayjs("2026-01-05").isoWeekday()).toBe(1);
  });

  it("registers isSameOrAfter / isSameOrBefore", () => {
    expect(typeof dayjs().isSameOrAfter).toBe("function");
    expect(typeof dayjs().isSameOrBefore).toBe("function");
    expect(dayjs("2026-01-05").isSameOrAfter(dayjs("2026-01-05"))).toBe(true);
    expect(dayjs("2026-01-05").isSameOrBefore(dayjs("2026-01-05"))).toBe(true);
  });

  it("registers customParseFormat (format-string parsing)", () => {
    const parsed = dayjs("05.01.2026", "DD.MM.YYYY");
    expect(parsed.isValid()).toBe(true);
    expect(parsed.format("YYYY-MM-DD")).toBe("2026-01-05");
  });
});
