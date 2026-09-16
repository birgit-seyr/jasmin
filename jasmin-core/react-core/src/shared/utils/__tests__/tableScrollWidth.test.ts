import { describe, expect, it } from "vitest";

import { calculateTableScrollWidth } from "../tableScrollWidth";

describe("calculateTableScrollWidth", () => {
  it("sums explicit em widths plus the additional padding", () => {
    const cols = [{ width: "10em" }, { width: "5em" }];
    expect(calculateTableScrollWidth(cols, 5)).toBe("20em");
  });

  it("recurses into children and sums their widths", () => {
    const cols = [
      { children: [{ width: "4em" }, { width: "6em" }] },
      { width: "5em" },
    ];
    // 4 + 6 + 5 = 15, plus default additionalWidth 5 = 20
    expect(calculateTableScrollWidth(cols)).toBe("20em");
  });

  it("ignores hidden columns", () => {
    const cols = [{ width: "10em" }, { width: "20em", hidden: true }];
    expect(calculateTableScrollWidth(cols, 0)).toBe("10em");
  });

  it("falls back to per-input-type defaults", () => {
    const cols = [
      { inputType: "date" }, // 10
      { inputType: "number" }, // 5
      { inputType: "select" }, // 12
      { inputType: "textarea" }, // 20
      { inputType: "checkbox", sorter: true }, // 4
      { inputType: "checkbox" }, // 2.5
      { inputType: "text" }, // 4
    ];
    // 10 + 5 + 12 + 20 + 4 + 2.5 + 4 = 57.5, plus default padding 5 = 62.5
    expect(calculateTableScrollWidth(cols)).toBe("62.5em");
  });

  it("uses 6em for any column whose dataIndex ends with 'unit'", () => {
    const cols = [{ dataIndex: "kg_unit" }, { dataIndex: "pieces_unit" }];
    expect(calculateTableScrollWidth(cols, 0)).toBe("12em");
  });

  it("uses an 8em fallback for unrecognised input types", () => {
    expect(
      calculateTableScrollWidth([{ inputType: "wat" as never }], 0),
    ).toBe("8em");
  });
});
