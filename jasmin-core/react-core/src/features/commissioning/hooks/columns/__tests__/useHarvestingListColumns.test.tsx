/**
 * useHarvestingListColumns: the office's grouped share/order columns, the
 * gardener's flat layout and the always-flat PDF columns, their amount cells
 * in the farm's number format at the unit's precision, and what stays
 * editable on which row and screen.
 */
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  carrotRow,
  crates,
  newRow,
  radishRow,
} from "./useHarvestingListColumns.fixtures";
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
}));

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  return {
    useTenant: () =>
      makeUseTenantMock({
        getSetting: (key: string, defaultValue?: unknown) =>
          key in tenantState.settings ? tenantState.settings[key] : defaultValue,
      }),
  };
});

const shareArticleQueries = vi.hoisted(() => [] as unknown[]);

vi.mock("@features/commissioning/hooks/useShareArticles", () => ({
  useShareArticles: (filters: unknown) => {
    shareArticleQueries.push(filters);
    return { shareArticles: [], loading: false };
  },
}));

vi.mock("@features/commissioning/hooks/useCrates", async () => {
  const fixtures = await import("./useHarvestingListColumns.fixtures");
  return { useCrates: () => ({ crates: fixtures.crates }) };
});

import { useHarvestingListColumns } from "../useHarvestingListColumns";

type View = { isMobile: boolean; isGardenerView: boolean };
const office: View = { isMobile: false, isGardenerView: false };
const gardener: View = { isMobile: false, isGardenerView: true };
const phone: View = { isMobile: true, isGardenerView: true };

const build = (view: View = office) =>
  renderHook(() => useHarvestingListColumns(view)).result.current;

const columnsFor = (view: View = office): Column[] => build(view).columns;

const groupChildren = (id: string, view: View = office): Column[] =>
  findColumn(columnsFor(view), id).children ?? [];

beforeEach(() => {
  tenantState.settings = { show_size_column: true };
  shareArticleQueries.length = 0;
});

describe("useHarvestingListColumns office layout", () => {
  it("lists article, unit, size, the five amount groups, per-PU, crate and note", () => {
    expect(columnIds(columnsFor())).toEqual([
      "share_article_name",
      "unit",
      "size",
      "theoretical_harvest_amount",
      "computed_still_in_stock",
      "computed_to_harvest",
      "amount",
      "amount_harvesting_list",
      "amount_per_pu",
      "harvesting_crate_name",
      "note",
    ]);
  });

  it("splits every amount group into a share-content and an order-content column", () => {
    const children = (id: string) =>
      groupChildren(id).map((column) => column.dataIndex);

    expect(children("theoretical_harvest_amount")).toEqual([
      "theoretical_harvest_amount_share_content",
      "theoretical_harvest_amount_order_content",
    ]);
    expect(children("computed_still_in_stock")).toEqual([
      "computed_still_in_stock_share_content",
      "computed_still_in_stock_order_content",
    ]);
    expect(children("computed_to_harvest")).toEqual([
      "computed_to_harvest_share_content",
      "computed_to_harvest_order_content",
    ]);
    expect(children("amount")).toEqual([
      "amount_share_content",
      "amount_order_content",
    ]);
    expect(children("amount_harvesting_list")).toEqual([
      "computed_amount_combined_share_content",
      "computed_amount_combined_order_content",
    ]);
  });

  it("starts each group, and its share-content column, a new column group", () => {
    for (const id of [
      "theoretical_harvest_amount",
      "computed_still_in_stock",
      "computed_to_harvest",
      "amount",
      "amount_harvesting_list",
    ]) {
      const [share, order] = groupChildren(id);
      expect(findColumn(columnsFor(), id).className).toBe("column-group-start");
      expect(share.className).toBe("column-group-start");
      expect(order.className).toBeUndefined();
    }
  });

  it("titles the children share content and order content", () => {
    const [share, order] = groupChildren("computed_to_harvest");

    expect(titleText(share.title)).toBe("commissioning.title_share_content");
    expect(titleText(order.title)).toBe("commissioning.title_order_content");
  });

  it("lets the office edit only the additional harvest of the amount columns", () => {
    for (const id of [
      "theoretical_harvest_amount",
      "computed_still_in_stock",
      "computed_to_harvest",
    ]) {
      for (const child of groupChildren(id)) {
        expect(isDisabled(child, carrotRow)).toBe(true);
        expect(child.hideInModal).toBe(true);
      }
    }
    for (const child of groupChildren("amount_harvesting_list")) {
      expect(isDisabled(child, carrotRow)).toBe(true);
    }
    for (const child of groupChildren("amount")) {
      expect(child.inputType).toBe("negative_integer");
      expect(isDisabled(child, carrotRow)).toBe(false);
      expect(child.hideInModal).toBe(false);
    }
  });

  it("marks stock and to-harvest read-only, the others not", () => {
    const readOnly = (id: string) => groupChildren(id).map((c) => c.readOnly);

    expect(readOnly("computed_still_in_stock")).toEqual([true, true]);
    expect(readOnly("computed_to_harvest")).toEqual([true, true]);
    expect(readOnly("theoretical_harvest_amount")).toEqual([undefined, undefined]);
    expect(readOnly("amount")).toEqual([undefined, undefined]);
  });

  it("shows the unit and size", () => {
    const columns = columnsFor();

    expect(findColumn(columns, "unit").hidden).toBe(false);
    expect(findColumn(columns, "size").hidden).toBe(false);
  });

  it("hides the size on a farm without sizes", () => {
    tenantState.settings = {};

    expect(findColumn(columnsFor(), "size").hidden).toBe(true);
  });

  it.each(["share_article_name", "unit", "size"])(
    "lets %s be chosen on a new row only",
    (key) => {
      const column = findColumn(columnsFor(), key);

      expect(isDisabled(column, newRow)).toBe(false);
      expect(isDisabled(column, carrotRow)).toBe(true);
    },
  );

  it("reapplies the article's per-PU defaults when the unit changes", () => {
    expect(typeof findColumn(columnsFor(), "unit").onFieldChange).toBe(
      "function",
    );
  });

  it("offers active harvested fruit and vegetables only", () => {
    const column = findColumn(columnsFor(), "share_article_name");

    expect(shareArticleQueries.at(-1)).toEqual({
      is_harvest_share_article: "true",
      is_active: "true",
      is_purchased: "false",
    });
    expect(column.title).toBe("commissioning.vegetables_and_fruits");
  });

  it("shows the article name as stored in the office layout", () => {
    expect(findColumn(columnsFor(), "share_article_name").render).toBeUndefined();
  });

  it("offers the farm's crates for the harvesting crate, writing the crate id", () => {
    const column = findColumn(columnsFor(), "harvesting_crate_name");

    expect(column.options).toEqual(crates);
    expect(column.foreignKey).toEqual({
      valueField: "harvesting_crate",
      displayField: "harvesting_crate_name",
    });
  });

  it("lets the office edit the note", () => {
    expect(isDisabled(findColumn(columnsFor(), "note"), carrotRow)).toBe(false);
  });
});

describe("useHarvestingListColumns amount cells", () => {
  it("shows a kilo amount at two decimals in the farm's format", () => {
    const [share] = groupChildren("theoretical_harvest_amount");

    expect(cellText(share, "12.5", carrotRow)).toBe("12,50");
    expect(cellText(share, 1234.5, carrotRow)).toBe("1.234,50");
  });

  it("shows a bunch amount at one decimal", () => {
    const [share] = groupChildren("theoretical_harvest_amount");

    expect(cellText(share, 30, radishRow)).toBe("30,0");
  });

  it("shows an amount without a unit at two decimals", () => {
    const [share] = groupChildren("computed_to_harvest");

    expect(cellText(share, 4, { key: "x" })).toBe("4,00");
  });

  it("follows the farm's number locale", () => {
    tenantState.settings = { show_size_column: true, number_locale: "en-US" };
    const [share] = groupChildren("theoretical_harvest_amount");

    expect(cellText(share, 1234.5, carrotRow)).toBe("1,234.50");
  });

  it.each([0, null, undefined, "", "n/a"])(
    "leaves an amount of %s blank",
    (value) => {
      const [, order] = groupChildren("computed_still_in_stock");

      expect(cellText(order, value, carrotRow)).toBe("");
    },
  );

  it("colours share content and order content apart", () => {
    const [share, order] = groupChildren("computed_to_harvest");

    expect(
      renderCell(share, 9.5, carrotRow).querySelector("span"),
    ).toHaveClass("text-share-content");
    expect(
      renderCell(order, 4, carrotRow).querySelector("span"),
    ).toHaveClass("text-order-content");
    expect(
      renderCell(order, 4, carrotRow).querySelector("span"),
    ).not.toHaveClass("text-bold");
  });

  it("shows the additional harvest, in bold, from its own field", () => {
    const [share, order] = groupChildren("amount");

    const shareCell = renderCell(share, 2, carrotRow);
    expect(shareCell.textContent).toBe("2,25");
    expect(shareCell.querySelector("span")).toHaveClass(
      "text-share-content",
      "text-bold",
    );
    expect(cellText(order, null, carrotRow)).toBe("");
  });

  it("shows the harvesting-list amount with its PU count below", () => {
    const [share] = groupChildren("amount_harvesting_list");

    const cell = renderCell(share, undefined, carrotRow);

    expect(cell.textContent).toBe("12,00 kg1 PU");
    expect(cell.querySelector("br")).not.toBeNull();
  });

  it("shows the harvesting-list amount alone when there is no PU count", () => {
    const [, order] = groupChildren("amount_harvesting_list");

    const cell = renderCell(order, undefined, carrotRow);

    expect(cell.textContent).toBe("4,00 kg");
    expect(cell.querySelector("br")).toBeNull();
  });

  it("leaves the harvesting-list amount blank for a row without one", () => {
    const [share] = groupChildren("amount_harvesting_list");

    expect(cellText(share, undefined, radishRow)).toBe("");
  });

  it.skip("colours the harvesting-list amounts by share and order content", () => {
    const [share, order] = groupChildren("amount_harvesting_list");

    const shareCell = renderCell(share, undefined, carrotRow).firstElementChild;
    const orderCell = renderCell(order, undefined, carrotRow).firstElementChild;

    expect(shareCell).toHaveClass("text-share-content");
    expect(orderCell).toHaveClass("text-order-content");
    expect((shareCell as HTMLElement).style.color).toBe("");
  });

  it("shows the per-PU hint, and nothing without one", () => {
    const column = findColumn(columnsFor(), "amount_per_pu");

    const cell = renderCell(column, undefined, carrotRow);
    expect(cell.textContent).toBe("12,00 kg/PU");
    expect(cell.firstElementChild).toHaveClass("text-hint-md");
    expect(renderCell(column, undefined, radishRow)).toBeEmptyDOMElement();
  });

  it("shows the note and the plot line on lines of their own", () => {
    const column = findColumn(columnsFor(), "note");

    const lines = renderCell(column, carrotRow.note, carrotRow).querySelectorAll(
      ".text-hint-md",
    );
    expect([...lines].map((line) => line.textContent)).toEqual([
      "vom Feld 3",
      "Feld 3, Beet 2",
    ]);
  });

  it("shows only the lines a row has", () => {
    const column = findColumn(columnsFor(), "note");

    expect(
      renderCell(column, null, { key: "x", computed_plot_line: "Feld 1" })
        .querySelectorAll(".text-hint-md"),
    ).toHaveLength(1);
    expect(
      renderCell(column, null, radishRow).querySelectorAll(".text-hint-md"),
    ).toHaveLength(0);
  });
});

describe("useHarvestingListColumns gardener and phone layouts", () => {
  it("shows the two harvesting-list amounts flat instead of the groups", () => {
    expect(columnIds(columnsFor(gardener))).toEqual([
      "share_article_name",
      "unit",
      "size",
      "amount_share_content_flat",
      "amount_order_content_flat",
      "amount_per_pu",
      "harvesting_crate_name",
      "note",
    ]);
  });

  it("titles the flat amounts by what they hold", () => {
    const columns = columnsFor(gardener);

    expect(titleText(findColumn(columns, "amount_share_content_flat").title)).toBe(
      "commissioning.amount_harvesting_list(commissioning.title_share_content)",
    );
    expect(findColumn(columns, "amount_share_content_flat").className).toBe(
      "column-group-start",
    );
    expect(
      findColumn(columns, "amount_order_content_flat").className,
    ).toBeUndefined();
  });

  it("shows a flat amount with its PU count, locked", () => {
    const column = findColumn(columnsFor(gardener), "amount_share_content_flat");

    expect(cellText(column, undefined, carrotRow)).toBe("12,00 kg1 PU");
    expect(isDisabled(column, carrotRow)).toBe(true);
  });

  it.each([
    ["gardener", gardener],
    ["phone", phone],
  ])("hides the unit and size on the %s screen", (_label, view) => {
    const columns = columnsFor(view);

    expect(findColumn(columns, "unit").hidden).toBe(true);
    expect(findColumn(columns, "size").hidden).toBe(true);
  });

  it("hides the office's grouped amounts on a phone in office layout", () => {
    const columns = columnsFor({ isMobile: true, isGardenerView: false });

    for (const child of groupChildren("computed_to_harvest", {
      isMobile: true,
      isGardenerView: false,
    })) {
      expect(child.hidden).toBe(true);
    }
    expect(findColumn(columns, "unit").hidden).toBe(true);
  });

  it.each([
    ["gardener", gardener],
    ["phone", phone],
  ])("locks the note on the %s screen", (_label, view) => {
    expect(isDisabled(findColumn(columnsFor(view), "note"), carrotRow)).toBe(
      true,
    );
  });

  it("adds a size other than medium to the article name", () => {
    const column = findColumn(columnsFor(gardener), "share_article_name");

    expect(cellText(column, "Karotten", carrotRow)).toBe(
      "Karotten (commissioning.large)",
    );
  });

  it("shows the article name alone for a medium size or none", () => {
    const column = findColumn(columnsFor(gardener), "share_article_name");

    expect(cellText(column, "Radieschen", radishRow)).toBe("Radieschen");
    expect(cellText(column, "Radieschen", { key: "x" })).toBe("Radieschen");
  });
});

describe("useHarvestingListColumns PDF columns", () => {
  it("prints the flat layout whatever the screen shows", () => {
    for (const view of [office, gardener]) {
      expect(columnIds(build(view).pdfColumns)).toEqual([
        "share_article_name",
        "amount_share_content_flat",
        "amount_order_content_flat",
        "amount_per_pu_pdf",
        "harvesting_crate_pdf",
        "note_pdf",
        "done_pdf",
      ]);
    }
  });

  it("prints the article with its size, the amounts and a tick box", () => {
    const { pdfColumns } = build();

    expect(findColumn(pdfColumns, "share_article_name").pdf).toMatchObject({
      include: true,
      dataKey: "computed_article_with_size",
      title: "commissioning.vegetables_and_fruits",
    });
    expect(findColumn(pdfColumns, "amount_order_content_flat").pdf).toMatchObject({
      include: true,
      dataKey: "computed_amount_combined_order_content",
      title: "commissioning.title_order_content",
    });
    expect(findColumn(pdfColumns, "done_pdf").pdf).toMatchObject({
      include: true,
      tickBox: true,
      title: "✓",
    });
  });

  it("prints the note and plot line on lines of their own", () => {
    const { pdfColumns } = build();
    const pdf = findColumn(pdfColumns, "note_pdf").pdf as {
      render: (record: unknown) => string;
    };

    expect(pdf.render(carrotRow)).toBe("vom Feld 3\nFeld 3, Beet 2");
    expect(pdf.render(radishRow)).toBe("");
  });

  it("prints the same note from the on-screen note column", () => {
    const pdf = findColumn(columnsFor(), "note").pdf as {
      include: boolean;
      render: (record: unknown) => string;
    };

    expect(pdf.include).toBe(true);
    expect(pdf.render({ key: "x", computed_note_line: "frisch" })).toBe("frisch");
  });

  it("keeps the unit, size and office-only amounts out of the printout", () => {
    const columns = columnsFor();

    expect(findColumn(columns, "unit").pdf).toEqual({ include: false });
    expect(findColumn(columns, "size").pdf).toEqual({ include: false });
    for (const child of groupChildren("computed_to_harvest")) {
      expect(child.pdf).toEqual({ include: false });
    }
    for (const child of groupChildren("amount_harvesting_list")) {
      expect(child.pdf).toMatchObject({ include: true, title: "commissioning.amount" });
    }
  });

  it("has no grouped amount columns in the printout", () => {
    expect(hasColumn(build().pdfColumns, "computed_to_harvest")).toBe(false);
  });
});
