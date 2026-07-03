import { describe, expect, it } from "vitest";

import {
  formatDayLabel,
  formatWeekLabel,
  generatePdfFilename,
} from "../filenameUtils";

/** Stand-in for i18next's `t`. */
const t = (key: string) => {
  if (key === "commissioning.KW") return "KW";
  // Mirror the de translation for weekday names so day-label tests are stable.
  const days: Record<string, string> = {
    "commissioning.weekdaysBIG.0": "Montag",
    "commissioning.weekdaysBIG.1": "Dienstag",
    "commissioning.weekdaysBIG.2": "Mittwoch",
    "commissioning.weekdaysBIG.3": "Donnerstag",
    "commissioning.weekdaysBIG.4": "Freitag",
    "commissioning.weekdaysBIG.5": "Samstag",
    "commissioning.weekdaysBIG.6": "Sonntag",
  };
  return days[key] ?? key;
};

describe("generatePdfFilename", () => {
  it("joins parts with underscores", () => {
    expect(generatePdfFilename(["invoice", 2024, "march"])).toBe(
      "invoice_2024_march",
    );
  });

  it("drops null, undefined, false and empty strings", () => {
    expect(
      generatePdfFilename(["a", null, undefined, false, "", "b"]),
    ).toBe("a_b");
  });

  it("replaces internal whitespace with underscores", () => {
    expect(generatePdfFilename(["delivery note", "week 12"])).toBe(
      "delivery_note_week_12",
    );
  });

  it("handles numeric parts", () => {
    expect(generatePdfFilename([2024, 12])).toBe("2024_12");
  });

  it("returns an empty string for an empty list", () => {
    expect(generatePdfFilename([])).toBe("");
  });
});

describe("formatWeekLabel", () => {
  it("prefixes with the translated KW token", () => {
    expect(formatWeekLabel(12, t)).toBe("KW12");
  });

  it("supports string week values", () => {
    expect(formatWeekLabel("3", t)).toBe("KW3");
  });

  it("returns empty string for null / undefined", () => {
    expect(formatWeekLabel(null, t)).toBe("");
    expect(formatWeekLabel(undefined, t)).toBe("");
  });
});

describe("formatDayLabel", () => {
  it("returns the sanitised translated day name", () => {
    expect(formatDayLabel(0, t)).toBe("Montag");
    expect(formatDayLabel(6, t)).toBe("Sonntag");
  });

  it("strips non-alphanumeric characters from the translation", () => {
    const tWithSpaces = (key: string) =>
      key === "commissioning.weekdaysBIG.0" ? "Mon-tag 1" : "x";
    expect(formatDayLabel(0, tWithSpaces)).toBe("Montag1");
  });

  it("returns empty string for null / undefined", () => {
    expect(formatDayLabel(null, t)).toBe("");
    expect(formatDayLabel(undefined, t)).toBe("");
  });
});
