/**
 * useBoxCombinationColumns: the packing boxes matrix's grouped columns — one
 * group per base share type (by its short name, in the backend's share-type
 * rank), one leaf per box combination (base size plus add-on badges), and
 * orphan add-on boxes under a "no base" group. The columns come in the order
 * the backend sorts them: share-type rank, sort order, size, add-on count, key.
 */
import { render, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import type { PackingBoxesMatrixAddOn, PackingBoxesMatrixColumn } from "@shared/api/generated/models";
import type { EditableColumnConfig, TableRecord } from "@shared/tables/BasicEditableTable/types";

// One `t` for every render, as react-i18next keeps it.
const i18nMock = vi.hoisted(() => ({
  t: (key: string, fallback?: unknown) => (typeof fallback === "string" ? fallback : key),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: i18nMock.t,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    getSetting: (key: string, defaultValue?: unknown) => (key === "number_locale" ? "de-DE" : defaultValue),
  });
  return { useTenant: () => tenant };
});

import { useBoxCombinationColumns } from "../useBoxCombinationColumns";

// ── Fixtures ────────────────────────────────────────────────────────────────

const addOn = (shortName: string, size: string, rank: number): PackingBoxesMatrixAddOn => ({
  variation_id: `v-${shortName}-${size}`,
  size,
  sort_order: 0,
  share_type_id: `st-${shortName}`,
  share_type_short_name: shortName,
  share_type_sort_index: rank,
});

type BaseShareType = { id: string; shortName: string; rank: number };

const VEG: BaseShareType = { id: "st-veg", shortName: "GEM", rank: 0 };
const FRUIT: BaseShareType = { id: "st-fruit", shortName: "OBST", rank: 1 };

function combination(
  key: string,
  base: BaseShareType,
  size: string,
  sortOrder: number,
  addOns: PackingBoxesMatrixAddOn[] = [],
): PackingBoxesMatrixColumn {
  return {
    key,
    base_variation_id: `v-${key}`,
    base_size: size,
    base_sort_order: sortOrder,
    base_share_type_id: base.id,
    base_share_type_name: base.shortName,
    base_share_type_short_name: base.shortName,
    base_share_type_sort_index: base.rank,
    add_ons: addOns,
    count: 1,
  };
}

/** Add-on boxes without a base box: they sort after every real base. */
const orphan = (key: string, addOns: PackingBoxesMatrixAddOn[], baseCount: number): PackingBoxesMatrixColumn => ({
  key,
  base_variation_id: null,
  base_size: "",
  base_sort_order: 0,
  base_share_type_id: null,
  base_share_type_name: "",
  base_share_type_short_name: "",
  base_share_type_sort_index: baseCount,
  add_ons: addOns,
  count: 1,
});

const HONEY_M = addOn("HONIG", "M", 0);
const BREAD_L = addOn("BROT", "L", 1);

// ── Helpers ─────────────────────────────────────────────────────────────────

const NO_BASE = "commissioning.no_base_combination";

const textOf = (node: ReactNode) => render(<>{node}</>).container.textContent;

/** Each group as [title, [leaf labels]]. */
const layout = (groups: EditableColumnConfig<TableRecord>[]) =>
  groups.map((group) => [group.title, (group.children ?? []).map((leaf) => textOf(leaf.title))]);

const columnsFor = (columns: PackingBoxesMatrixColumn[], options?: Parameters<typeof useBoxCombinationColumns>[1]) =>
  renderHook(() => useBoxCombinationColumns(columns, options)).result.current;

// ── Groups and leaves ───────────────────────────────────────────────────────

describe("useBoxCombinationColumns layout", () => {
  it("groups combinations under their base share type, in the share types' rank", () => {
    const groups = columnsFor([
      combination("c-fruit-m", FRUIT, "M", 0),
      combination("c-veg-s", VEG, "S", 0),
      combination("c-veg-m", VEG, "M", 1),
    ]);

    expect(layout(groups)).toEqual([
      ["GEM", ["commissioning.S", "commissioning.M"]],
      ["OBST", ["commissioning.M"]],
    ]);
    expect(groups.map((g) => [g.key, g.dataIndex, g.align])).toEqual([
      ["group_st-veg", "group_st-veg", "center"],
      ["group_st-fruit", "group_st-fruit", "center"],
    ]);
  });

  it("labels a combination by its base size with one badge per add-on, plain boxes first", () => {
    const groups = columnsFor([
      combination("c-veg-m-honey-bread", VEG, "M", 1, [HONEY_M, BREAD_L]),
      combination("c-veg-m-honey", VEG, "M", 1, [HONEY_M]),
      combination("c-veg-m", VEG, "M", 1),
    ]);

    expect(layout(groups)).toEqual([
      [
        "GEM",
        ["commissioning.M", "commissioning.MHONIG·commissioning.M", "commissioning.MHONIG·commissioning.MBROT·commissioning.L"],
      ],
    ]);
  });

  it("puts add-on boxes without a base under a 'no base' group after the real ones", () => {
    const groups = columnsFor([
      orphan("c-none-honey", [HONEY_M], 2),
      combination("c-fruit-m", FRUIT, "M", 0),
      combination("c-veg-m", VEG, "M", 0),
    ]);

    expect(layout(groups)).toEqual([
      ["GEM", ["commissioning.M"]],
      ["OBST", ["commissioning.M"]],
      [NO_BASE, [`${NO_BASE}HONIG·commissioning.M`]],
    ]);
    expect(groups[2].key).toBe("group___none__");
  });

  it("keys each leaf by its combination and gives it the asked-for width", () => {
    const [group] = columnsFor([combination("combo_v1|", VEG, "M", 0)], { width: "7em" });

    expect(group.children?.[0]).toMatchObject({ key: "combo_v1|", dataIndex: "combo_v1|", align: "center", width: "7em" });
  });

  it("has no columns for a scope without boxes", () => {
    expect(columnsFor([])).toEqual([]);
  });

  it("keeps the backend's size order for sizes that share a sort order", () => {
    // Variations default to sort order 0; the backend then orders by size.
    const groups = columnsFor([
      combination("combo_zz-small|", VEG, "S", 0),
      combination("combo_mm-medium|", VEG, "M", 0),
      combination("combo_aa-large|", VEG, "L", 0),
    ]);

    expect(layout(groups)).toEqual([["GEM", ["commissioning.S", "commissioning.M", "commissioning.L"]]]);
  });
});

// ── Cells ───────────────────────────────────────────────────────────────────

describe("useBoxCombinationColumns cells", () => {
  const leaf = (options?: Parameters<typeof useBoxCombinationColumns>[1]) =>
    columnsFor([combination("c-veg-m", VEG, "M", 0)], options)[0].children![0];
  const record: TableRecord = { key: "st-hof", id: "st-hof", "c-veg-m": 1200 };

  it.each([
    [1200, "1.200"],
    ["7", "7"],
    [2.6, "3"],
    [0, ""],
    ["0", ""],
    [null, ""],
    [undefined, ""],
    ["n/a", ""],
  ])("shows %s boxes as %j", (value, shown) => {
    expect(leaf().render?.(value, record, 0)).toBe(shown);
  });

  it("draws the cells with the caller's renderer when given one", () => {
    const renderCell = vi.fn(() => "x");

    expect(leaf({ renderCell }).render?.(4, record, 3)).toBe("x");
    expect(renderCell).toHaveBeenCalledWith(4, record, 3);
  });

  it("keeps the columns while the input stays the same", () => {
    const input = [combination("c-veg-m", VEG, "M", 0)];
    const { result, rerender } = renderHook(() => useBoxCombinationColumns(input));
    const first = result.current;

    rerender();

    expect(result.current).toBe(first);
  });
});
