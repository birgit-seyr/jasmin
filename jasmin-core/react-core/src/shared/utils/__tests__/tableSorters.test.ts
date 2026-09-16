import { describe, expect, it } from "vitest";

import {
  createBooleanSorter,
  createDateSorter,
  createNumberSorter,
  createStringSorter,
} from "../tableSorters";

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
