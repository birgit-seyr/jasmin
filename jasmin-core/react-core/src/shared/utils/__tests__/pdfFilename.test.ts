import { describe, expect, it } from "vitest";

import { generatePdfFilename } from "../pdfFilename";

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
