/**
 * useShareArticleListColumns: the share-article list's column set per tenant
 * flag and share-option filter, the cells' number and unit display in the
 * farm's number format, and which cells lock for which rows.
 */
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  baseArgs,
  crates,
  harvestedArticle,
  newArticle,
  priceModalColumn,
  purchasedArticle,
} from "./useShareArticleListColumns.fixtures";
import {
  cellText,
  columnIds,
  findColumn,
  hasColumn,
  isDisabled,
  renderCell,
  titleText,
  type Column,
} from "./columnTestHelpers";

// One translation object for every render, as the real i18next hands out, so
// the hook's memo can hold across rerenders.
const translation = vi.hoisted(() => ({
  t: (key: string, fallback?: unknown) =>
    typeof fallback === "string" ? fallback : key,
  i18n: { language: "de", changeLanguage: () => Promise.resolve() },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => translation,
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const tenantState = vi.hoisted(() => ({
  settings: {} as Record<string, unknown>,
  tenant: null as Record<string, unknown> | null,
}));

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  return {
    useTenant: () =>
      makeUseTenantMock({
        tenant: tenantState.tenant,
        getSetting: (key: string, defaultValue?: unknown) =>
          key in tenantState.settings ? tenantState.settings[key] : defaultValue,
      }),
  };
});

import { useShareArticleListColumns } from "../useShareArticleListColumns";

type Args = Parameters<typeof useShareArticleListColumns>[0];

const buildColumns = (overrides: Partial<Args> = {}): Column[] =>
  renderHook(() => useShareArticleListColumns({ ...baseArgs, ...overrides }))
    .result.current;

beforeEach(() => {
  tenantState.settings = {};
  tenantState.tenant = null;
});

describe("useShareArticleListColumns column set", () => {
  it("lists the columns in order for a farm without prices button, organic status or bulk packing", () => {
    expect(columnIds(buildColumns())).toEqual([
      "is_active",
      "article_number",
      "name",
      "default_movement_unit",
      "is_purchased",
      "description",
      "harvest_share",
      "harvest_share_fruit",
      "is_sold_to_resellers",
      "for_markets",
      "kg_per_piece_S",
      "kg_per_piece_M",
      "kg_per_piece_L",
      "pieces_per_kg_S",
      "pieces_per_kg_M",
      "pieces_per_kg_L",
      "default_packing_station",
      "percentage_added_to_commissioning_list_packing",
      "default_kg_per_pu_harvest",
      "default_pieces_per_pu_harvest",
      "default_bunches_per_pu_harvest",
      "default_crate_harvest_name",
      "default_commissioning_unit",
      "default_kg_per_pu_reseller",
      "default_pieces_per_pu_reseller",
      "default_bunches_per_pu_reseller",
      "default_crate_reseller_name",
      "default_kg_per_pu_purchase",
      "default_pieces_per_pu_purchase",
      "default_bunches_per_pu_purchase",
    ]);
  });

  it("puts the page's active column first, unchanged", () => {
    expect(buildColumns()[0]).toBe(baseArgs.isActiveColumn);
  });

  it("puts the prices button right after the name when the page passes one", () => {
    const ids = columnIds(buildColumns({ priceModalColumn }));

    expect(ids.slice(1, 5)).toEqual([
      "article_number",
      "name",
      "prices",
      "default_movement_unit",
    ]);
  });

  it("leaves the prices button out without one", () => {
    expect(hasColumn(buildColumns(), "prices")).toBe(false);
  });

  it("shows the organic status after the purchased flag on a certified farm", () => {
    tenantState.tenant = { organic_control_number: "AT-BIO-301" };

    const ids = columnIds(buildColumns());

    expect(ids.indexOf("organic_status")).toBe(ids.indexOf("is_purchased") + 1);
  });

  it("labels each organic status and shows a dash for none", () => {
    tenantState.tenant = { organic_control_number: "AT-BIO-301" };
    const column = findColumn(buildColumns(), "organic_status");

    expect(cellText(column, "in_conversion", harvestedArticle)).toBe(
      "commissioning.organic.in_conversion",
    );
    expect(cellText(column, null, harvestedArticle)).toBe("-");
  });

  it.each([
    ["no control number", null],
    ["a blank control number", { organic_control_number: "   " }],
  ])("leaves the organic status out with %s", (_label, tenant) => {
    tenantState.tenant = tenant;

    expect(hasColumn(buildColumns(), "organic_status")).toBe(false);
  });

  it("adds the bulk packing percentage before the commissioning percentage when the farm packs in bulk", () => {
    const ids = columnIds(buildColumns({ packingBulk: true }));

    expect(ids.indexOf("percentage_added_to_bulk_packing_list")).toBe(
      ids.indexOf("percentage_added_to_commissioning_list_packing") - 1,
    );
  });

  it("leaves the bulk packing percentage out otherwise", () => {
    expect(
      hasColumn(buildColumns(), "percentage_added_to_bulk_packing_list"),
    ).toBe(false);
  });

  it("hides the reseller and market flags on a farm without them", () => {
    const columns = buildColumns({
      sells_to_resellers: false,
      has_markets: false,
    });

    expect(findColumn(columns, "is_sold_to_resellers").hidden).toBe(true);
    expect(findColumn(columns, "for_markets").hidden).toBe(true);
  });

  it("shows the reseller and market flags on a farm with them", () => {
    const columns = buildColumns();

    expect(findColumn(columns, "is_sold_to_resellers").hidden).toBe(false);
    expect(findColumn(columns, "for_markets").hidden).toBe(false);
  });

  it("requires only the name and the movement unit", () => {
    const required = buildColumns()
      .filter((column) => column.required)
      .map((column) => column.key);

    expect(required).toEqual(["name", "default_movement_unit"]);
  });
});

describe("useShareArticleListColumns share-option columns", () => {
  it("gives each visible share option a checkbox titled by its label", () => {
    const column = findColumn(buildColumns(), "harvest_share_fruit");

    expect(column.inputType).toBe("checkbox");
    expect(column.dataIndex).toBe("harvest_share_fruit");
    expect(titleText(column.title)).toBe(
      "commissioning.share_option.HARVEST_SHARE_FRUIT",
    );
  });

  it("starts the share-option group at the first option only", () => {
    const columns = buildColumns();

    expect(findColumn(columns, "harvest_share").className).toBe(
      "column-group-start",
    );
    expect(findColumn(columns, "harvest_share_fruit").className).toBeUndefined();
  });

  it("keeps only the filtered option's column, starting the group", () => {
    const columns = buildColumns({ activeFilter: "harvest_share_fruit" });

    expect(hasColumn(columns, "harvest_share")).toBe(false);
    expect(findColumn(columns, "harvest_share_fruit").className).toBe(
      "column-group-start",
    );
  });

  it("shows no share-option column for a filter matching none", () => {
    const columns = buildColumns({ activeFilter: "honey_share" });

    expect(columns.some((column) => column.key === "harvest_share")).toBe(false);
    expect(
      columns.some((column) => column.key === "harvest_share_fruit"),
    ).toBe(false);
  });

  it("shows no share-option column when the farm offers none", () => {
    const ids = columnIds(buildColumns({ visibleShareOptions: [] }));

    expect(ids.indexOf("is_sold_to_resellers")).toBe(
      ids.indexOf("description") + 1,
    );
  });

  it("rebuilds the columns when the filter changes", () => {
    const { result, rerender } = renderHook(
      (props: Args) => useShareArticleListColumns(props),
      { initialProps: baseArgs },
    );
    const before = result.current;

    rerender(baseArgs);
    expect(result.current).toBe(before);

    rerender({ ...baseArgs, activeFilter: "harvest_share" });
    expect(result.current).not.toBe(before);
    expect(hasColumn(result.current, "harvest_share_fruit")).toBe(false);
  });
});

describe("useShareArticleListColumns cells", () => {
  it("shows a unit by its label and an unknown unit as stored", () => {
    const columns = buildColumns();

    for (const key of ["default_movement_unit", "default_commissioning_unit"]) {
      const column = findColumn(columns, key);
      expect(cellText(column, "BUNCH", harvestedArticle)).toBe("Bund");
      expect(cellText(column, "LITRE", harvestedArticle)).toBe("LITRE");
    }
  });

  it("offers the page's units for both unit columns", () => {
    const columns = buildColumns();

    expect(findColumn(columns, "default_movement_unit").options).toBe(
      baseArgs.unitOptions,
    );
    expect(findColumn(columns, "default_commissioning_unit").options).toBe(
      baseArgs.unitOptions,
    );
  });

  it.each(["kg_per_piece_S", "kg_per_piece_M", "kg_per_piece_L", "default_kg_per_pu_reseller"])(
    "shows %s at three decimals in the farm's format",
    (key) => {
      const column = findColumn(buildColumns(), key);

      expect(cellText(column, "0.125", harvestedArticle)).toBe("0,125");
      expect(cellText(column, 1234.5, harvestedArticle)).toBe("1.234,500");
    },
  );

  it("follows the farm's number locale", () => {
    tenantState.settings = { number_locale: "en-US" };
    const column = findColumn(buildColumns(), "kg_per_piece_M");

    expect(cellText(column, "1234.5", harvestedArticle)).toBe("1,234.500");
  });

  it.each([
    "pieces_per_kg_S",
    "pieces_per_kg_M",
    "pieces_per_kg_L",
    "default_pieces_per_pu_reseller",
    "default_bunches_per_pu_reseller",
  ])("shows %s as a whole number", (key) => {
    const column = findColumn(buildColumns(), key);

    expect(cellText(column, 1200, harvestedArticle)).toBe("1.200");
  });

  it.each([null, undefined, "", "n/a"])(
    "leaves a number cell blank for %s",
    (value) => {
      const columns = buildColumns();

      expect(cellText(findColumn(columns, "kg_per_piece_S"), value, harvestedArticle)).toBe("");
      expect(cellText(findColumn(columns, "pieces_per_kg_S"), value, harvestedArticle)).toBe("");
    },
  );

  it("shows zero in a number cell", () => {
    const column = findColumn(buildColumns(), "kg_per_piece_S");

    expect(cellText(column, 0, harvestedArticle)).toBe("0,000");
  });

  it.each([
    "percentage_added_to_commissioning_list_packing",
    "percentage_added_to_bulk_packing_list",
  ])("shows %s as a whole percentage, blank for none", (key) => {
    const column = findColumn(buildColumns({ packingBulk: true }), key);

    expect(cellText(column, 15, harvestedArticle)).toBe("15 %");
    expect(cellText(column, "12.6", harvestedArticle)).toBe("13 %");
    expect(cellText(column, 0, harvestedArticle)).toBe("");
    expect(cellText(column, null, harvestedArticle)).toBe("");
  });

  it("offers one packing station per station the farm runs", () => {
    expect(
      findColumn(buildColumns({ number_packing_stations: 3 }), "default_packing_station").options,
    ).toEqual([
      { label: 1, value: 1 },
      { label: 2, value: 2 },
      { label: 3, value: 3 },
    ]);
  });

  it("offers no packing station when the farm runs none", () => {
    expect(
      findColumn(buildColumns({ number_packing_stations: 0 }), "default_packing_station").options,
    ).toEqual([]);
  });

  it("offers the page's crates for both default crates, writing the crate id", () => {
    const columns = buildColumns();
    const harvest = findColumn(columns, "default_crate_harvest_name");
    const reseller = findColumn(columns, "default_crate_reseller_name");

    expect(harvest.options).toBe(crates);
    expect(reseller.options).toBe(crates);
    expect(harvest.foreignKey).toEqual({
      valueField: "default_crate_harvest",
      displayField: "default_crate_harvest_name",
    });
    expect(reseller.foreignKey).toEqual({
      valueField: "default_crate_reseller",
      displayField: "default_crate_reseller_name",
    });
  });

  it("shows a harvested article's harvest crate", () => {
    const column = findColumn(buildColumns(), "default_crate_harvest_name");

    expect(cellText(column, "E2", harvestedArticle)).toBe("E2");
  });

  it("blanks a purchased article's harvest crate, and a missing crate", () => {
    const column = findColumn(buildColumns(), "default_crate_harvest_name");

    expect(renderCell(column, "E2", purchasedArticle)).toBeEmptyDOMElement();
    expect(renderCell(column, undefined, harvestedArticle)).toBeEmptyDOMElement();
  });

  it("hands the harvest and purchase cells to the page's renderers at their precision", () => {
    const harvestCalls: number[] = [];
    const purchaseCalls: number[] = [];
    const columns = buildColumns({
      renderHarvestNumber: (decimals) => {
        harvestCalls.push(decimals);
        return (value) => `h${value}@${decimals}`;
      },
      renderPurchaseNumber: (decimals) => {
        purchaseCalls.push(decimals);
        return (value) => `p${value}@${decimals}`;
      },
    });

    expect(harvestCalls).toEqual([3, 0, 0]);
    expect(purchaseCalls).toEqual([3, 0, 0]);
    expect(
      cellText(findColumn(columns, "default_kg_per_pu_harvest"), "12.5", harvestedArticle),
    ).toBe("h12.5@3");
    expect(
      cellText(findColumn(columns, "default_bunches_per_pu_purchase"), 4, purchasedArticle),
    ).toBe("p4@0");
  });
});

describe("useShareArticleListColumns locked cells", () => {
  const lockedUnlessDeletable = ["name", "default_movement_unit", "is_purchased"];

  it.each(lockedUnlessDeletable)(
    "locks %s on an article that is in use",
    (key) => {
      expect(isDisabled(findColumn(buildColumns(), key), harvestedArticle)).toBe(true);
    },
  );

  it.each(lockedUnlessDeletable)(
    "leaves %s editable on an unused article, a new one and one without the flag",
    (key) => {
      const column = findColumn(buildColumns(), key);

      expect(isDisabled(column, purchasedArticle)).toBe(false);
      expect(isDisabled(column, { ...harvestedArticle, key: -1 })).toBe(false);
      expect(isDisabled(column, { key: "sa-x", can_be_deleted: null })).toBe(false);
    },
  );

  const harvestKeys = [
    "default_kg_per_pu_harvest",
    "default_pieces_per_pu_harvest",
    "default_bunches_per_pu_harvest",
    "default_crate_harvest_name",
  ];
  const purchaseKeys = [
    "default_kg_per_pu_purchase",
    "default_pieces_per_pu_purchase",
    "default_bunches_per_pu_purchase",
  ];

  it.each(harvestKeys)("locks %s on a purchased article only", (key) => {
    const column = findColumn(buildColumns(), key);

    expect(isDisabled(column, purchasedArticle)).toBe(true);
    expect(isDisabled(column, harvestedArticle)).toBe(false);
  });

  it.each(purchaseKeys)("locks %s on a harvested article only", (key) => {
    const column = findColumn(buildColumns(), key);

    expect(isDisabled(column, harvestedArticle)).toBe(true);
    expect(isDisabled(column, purchasedArticle)).toBe(false);
  });

  it.each([...harvestKeys, ...purchaseKeys])(
    "leaves %s editable on a new article not yet marked either way",
    (key) => {
      expect(isDisabled(findColumn(buildColumns(), key), newArticle)).toBe(false);
    },
  );

  it.each([
    "article_number",
    "description",
    "kg_per_piece_S",
    "default_commissioning_unit",
    "default_kg_per_pu_reseller",
    "default_crate_reseller_name",
  ])("never locks %s", (key) => {
    const column = findColumn(buildColumns(), key);

    expect(isDisabled(column, harvestedArticle)).toBe(false);
    expect(isDisabled(column, purchasedArticle)).toBe(false);
  });
});
