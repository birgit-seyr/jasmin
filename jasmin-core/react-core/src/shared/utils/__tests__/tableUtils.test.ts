import { describe, expect, it } from "vitest";

import {
  calculateTableScrollWidth,
  createBooleanSorter,
  createDateSorter,
  createNumberSorter,
  createStringSorter,
} from "../tableUtils";

describe("createStringSorter", () => {
  const sorter = createStringSorter("name");

  it("sorts ascending by locale order", () => {
    const rows = [{ name: "Charlie" }, { name: "alice" }, { name: "Bob" }];
    rows.sort(sorter);
    expect(rows.map((r) => r.name)).toEqual(["alice", "Bob", "Charlie"]);
  });

  it("treats null/undefined as empty string", () => {
    const rows = [{ name: "x" }, { name: null }, { name: undefined }];
    rows.sort(sorter);
    expect(rows[0].name == null || rows[0].name === undefined).toBe(true);
  });
});

describe("createNumberSorter", () => {
  const sorter = createNumberSorter("n");

  it("sorts ascending numerically", () => {
    const rows = [{ n: 30 }, { n: 2 }, { n: 100 }];
    rows.sort(sorter);
    expect(rows.map((r) => r.n)).toEqual([2, 30, 100]);
  });

  it("treats falsy as 0", () => {
    const rows = [{ n: 5 }, { n: 0 }, { n: null }, { n: -2 }];
    rows.sort(sorter);
    expect(rows.map((r) => r.n)).toEqual([-2, 0, null, 5]);
  });
});

describe("createBooleanSorter", () => {
  it("puts true first by default", () => {
    const rows = [{ b: false }, { b: true }, { b: false }, { b: true }];
    rows.sort(createBooleanSorter("b"));
    expect(rows.map((r) => r.b)).toEqual([true, true, false, false]);
  });

  it("puts false first when trueFirst=false", () => {
    const rows = [{ b: true }, { b: false }];
    rows.sort(createBooleanSorter("b", false));
    expect(rows.map((r) => r.b)).toEqual([false, true]);
  });

  it("treats truthy/falsy values consistently", () => {
    const rows = [{ b: 0 }, { b: "yes" }, { b: null }];
    rows.sort(createBooleanSorter("b"));
    expect(!!rows[0].b).toBe(true);
  });
});

describe("createDateSorter", () => {
  it("sorts ascending by date value", () => {
    const rows = [
      { d: "2024-03-01" },
      { d: "2024-01-15" },
      { d: "2024-02-10" },
    ];
    rows.sort(createDateSorter("d"));
    expect(rows.map((r) => r.d)).toEqual([
      "2024-01-15",
      "2024-02-10",
      "2024-03-01",
    ]);
  });

  it("places nulls last by default", () => {
    const rows = [
      { d: null },
      { d: "2024-01-01" },
      { d: undefined },
      { d: "2023-12-31" },
    ];
    rows.sort(createDateSorter("d"));
    expect(rows[0].d).toBe("2023-12-31");
    expect(rows[1].d).toBe("2024-01-01");
    // last two are null/undefined in some order
    expect(rows.slice(2).every((r) => r.d == null)).toBe(true);
  });

  it("places nulls first when nullsLast=false", () => {
    const rows = [{ d: "2024-01-01" }, { d: null }];
    rows.sort(createDateSorter("d", false));
    expect(rows[0].d).toBeNull();
  });

  it("returns 0 when both sides are null", () => {
    expect(createDateSorter("d")({ d: null }, { d: null })).toBe(0);
  });
});

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
