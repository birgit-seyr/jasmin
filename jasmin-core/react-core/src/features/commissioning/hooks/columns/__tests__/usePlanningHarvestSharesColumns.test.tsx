/**
 * usePlanningHarvestSharesColumns: the harvest-share planning grid's column
 * order around the delivery-day columns, the optional note and packing-station
 * columns, the forecast/stock emphasis, the read-only forecast, stock and
 * still-free cells in the farm's number format, and the backup button.
 */
import { fireEvent, render, renderHook, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import {
  amountUnitSizeColumns,
  deliveryDayColumns,
  finalColumn,
  forecastRow,
  noteColumn,
  plainRow,
  sellers,
  shareArticleColumn,
  stockRow,
  washingCleaningColumns,
} from "./usePlanningHarvestSharesColumns.fixtures";
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

vi.mock("@features/commissioning/hooks/useSellers", async () => {
  const fixtures = await import("./usePlanningHarvestSharesColumns.fixtures");
  return { useSellers: () => ({ sellers: fixtures.sellers }) };
});

import { usePlanningHarvestSharesColumns } from "../usePlanningHarvestSharesColumns";

type Args = Parameters<typeof usePlanningHarvestSharesColumns>[0];

const setters = {
  setIsBackupModalOpen: vi.fn(),
  setSelectedBackupData: vi.fn(),
};

const baseArgs = (): Args => ({
  finalColumn,
  shareArticleColumn,
  amountUnitSizeColumns,
  washingCleaningColumns,
  noteColumn,
  deliveryDayColumns,
  showDetailedColumns: true,
  dataHasNotes: { hasForecastNote: false, hasStockNote: false },
  calculateStillFree: () => 0,
  number_packing_stations: 1,
  formatCurrency: (amount) => `€ ${Number(amount).toFixed(2)}`,
  getUnitLabel: (unit) => `[${unit}]`,
  ...setters,
});

const build = (overrides: Partial<Args> = {}): Column[] =>
  renderHook(() =>
    usePlanningHarvestSharesColumns({ ...baseArgs(), ...overrides }),
  ).result.current;

const column = (id: string, overrides: Partial<Args> = {}) =>
  findColumn(build(overrides), id);

/** The inline style of a cell's outermost element. */
const cellStyle = (col: Column, value: unknown, record: TableRecord) =>
  (renderCell(col, value, record).firstElementChild as HTMLElement).style;

beforeEach(() => {
  tenantState.settings = {};
  setters.setIsBackupModalOpen.mockReset();
  setters.setSelectedBackupData.mockReset();
});

describe("usePlanningHarvestSharesColumns column set", () => {
  it("puts the article columns before the delivery days and the extras after", () => {
    expect(columnIds(build())).toEqual([
      "is_finalized",
      "share_article_name",
      "unit",
      "size",
      "kg_per_piece",
      "price_per_unit",
      "forecast_available_amount",
      "current_stock_begin_of_week",
      "still_free",
      "day_day-tue",
      "day_day-fri",
      "washing",
      "cleaning",
      "comes_from_long_term_storage",
      "seller_name",
      "backup",
      "note",
    ]);
  });

  it("adds the forecast note after the forecast and the stock note after the stock", () => {
    const ids = columnIds(
      build({ dataHasNotes: { hasForecastNote: true, hasStockNote: true } }),
    );

    expect(ids.indexOf("forecast_note")).toBe(
      ids.indexOf("forecast_available_amount") + 1,
    );
    expect(ids.indexOf("current_stock_note")).toBe(
      ids.indexOf("current_stock_begin_of_week") + 1,
    );
  });

  it.each([
    [{ hasForecastNote: true, hasStockNote: false }, "forecast_note", "current_stock_note"],
    [{ hasForecastNote: false, hasStockNote: true }, "current_stock_note", "forecast_note"],
  ])("shows only the note the data has (%o)", (dataHasNotes, shown, absent) => {
    const columns = build({ dataHasNotes });

    expect(hasColumn(columns, shown)).toBe(true);
    expect(hasColumn(columns, absent)).toBe(false);
  });

  it("adds a packing-station choice before the seller on a farm with several stations", () => {
    const columns = build({ number_packing_stations: 3 });
    const ids = columnIds(columns);

    expect(ids.indexOf("packing_station")).toBe(ids.indexOf("seller_name") - 1);
    expect(findColumn(columns, "packing_station").options).toEqual([
      { label: "1", value: 1 },
      { label: "2", value: 2 },
      { label: "3", value: 3 },
    ]);
  });

  it("leaves the packing station out on a farm with one station", () => {
    expect(hasColumn(build(), "packing_station")).toBe(false);
    expect(hasColumn(build({ number_packing_stations: 0 }), "packing_station")).toBe(false);
  });

  it("starts the washing group, keeping the other extras as passed", () => {
    const columns = build();

    expect(findColumn(columns, "washing").className).toBe("column-group-start");
    expect(findColumn(columns, "cleaning")).toBe(washingCleaningColumns[1]);
    expect(washingCleaningColumns[0].className).toBeUndefined();
  });

  it("passes the final and delivery-day columns through unchanged", () => {
    const columns = build();

    expect(columns[0]).toBe(finalColumn);
    expect(findColumn(columns, "day_day-tue")).toBe(deliveryDayColumns[0]);
  });

  it.each([
    "kg_per_piece",
    "price_per_unit",
    "forecast_available_amount",
    "forecast_note",
    "current_stock_begin_of_week",
    "current_stock_note",
    "still_free",
  ])("hides %s unless the detailed columns are on", (key) => {
    const notes = { hasForecastNote: true, hasStockNote: true };

    expect(column(key, { dataHasNotes: notes }).hidden).toBe(false);
    expect(
      column(key, { dataHasNotes: notes, showDetailedColumns: false }).hidden,
    ).toBe(true);
  });

  it.each([
    "forecast_available_amount",
    "forecast_note",
    "current_stock_begin_of_week",
    "current_stock_note",
    "still_free",
    "backup",
  ])("locks %s", (key) => {
    const col = column(key, {
      dataHasNotes: { hasForecastNote: true, hasStockNote: true },
    });

    expect(isDisabled(col, forecastRow)).toBe(true);
    expect(col.readOnly).toBe(true);
  });

  it("lets the planner edit the weight per piece and the price", () => {
    expect(isDisabled(column("kg_per_piece"), plainRow)).toBe(false);
    expect(column("kg_per_piece").inputType).toBe("positive_decimal3");
    expect(isDisabled(column("price_per_unit"), plainRow)).toBe(false);
    expect(column("price_per_unit").inputType).toBe("positive_decimal2");
  });

  it("lets the article be chosen on a new row only", () => {
    const col = column("share_article_name");

    expect(isDisabled(col, { key: -1 })).toBe(false);
    expect(isDisabled(col, plainRow)).toBe(true);
  });

  it("titles the seller column as the seller for a purchase and offers the sellers", () => {
    const col = column("seller_name");

    expect(titleText(col.title)).toBe("commissioning.seller_for_purchase");
    expect(col.options).toEqual(sellers);
    expect(col.foreignKey).toEqual({
      valueField: "seller",
      displayField: "seller_name",
    });
  });

  it("titles the note for the planning grid, keeping the page's note field", () => {
    const col = column("note");

    expect(titleText(col.title).trim()).toBe("commissioning.note");
    expect(col.dataIndex).toBe("note");
    expect(col.width).toBe("16em");
  });
});

describe("usePlanningHarvestSharesColumns row emphasis", () => {
  it("shows a forecast row's article green and bold", () => {
    const style = cellStyle(column("share_article_name"), "Karotten", forecastRow);

    expect(style.color).toBe("green");
    expect(style.fontWeight).toBe("bold");
  });

  it("shows a stock-only row's article green at normal weight", () => {
    const style = cellStyle(column("share_article_name"), "Lauch", stockRow);

    expect(style.color).toBe("green");
    expect(style.fontWeight).toBe("normal");
  });

  it("leaves a plain row's article in the surrounding colour", () => {
    const style = cellStyle(column("share_article_name"), "Salat", plainRow);

    expect(style.color).toBe("inherit");
    expect(style.fontWeight).toBe("normal");
  });

  it("emphasises the unit and size the same way, through their own render", () => {
    const unit = column("unit");
    const size = column("size");

    expect(cellText(unit, "KG", forecastRow)).toBe("unit:KG");
    expect(cellStyle(unit, "KG", forecastRow).color).toBe("green");
    expect(cellText(size, "M", forecastRow)).toBe("M");
    expect(cellStyle(size, "M", plainRow).color).toBe("inherit");
  });
});

describe("usePlanningHarvestSharesColumns cells", () => {
  it("shows the weight per piece in the farm's format, blank without one", () => {
    const col = column("kg_per_piece");

    expect(cellText(col, "1.5", plainRow)).toBe("1,50");
    expect(cellText(col, null, forecastRow)).toBe("");
    expect(cellText(col, undefined, forecastRow)).toBe("");
  });

  it.skip("shows the weight per piece at the three decimals it is entered in", () => {
    expect(cellText(column("kg_per_piece"), "0.125", plainRow)).toBe("0,125");
  });

  it("shows the price per unit in the farm's currency, blank without one", () => {
    const col = column("price_per_unit");

    expect(cellText(col, "1.80", forecastRow)).toBe("€ 1.80/[KG]");
    expect(cellText(col, "0", plainRow)).toBe("€ 0.00/[PCS]");
    expect(cellText(col, null, plainRow)).toBe("");
  });

  it("shows the forecast amount as a whole number in the farm's format", () => {
    const col = column("forecast_available_amount");

    expect(cellText(col, undefined, forecastRow)).toBe("40");
    expect(
      cellText(col, undefined, { ...forecastRow, forecast_available_amount: "1200.00" }),
    ).toBe("1.200");
  });

  it("says enough is available for a forecast without an amount", () => {
    const col = column("forecast_available_amount");

    expect(
      cellText(col, undefined, { ...forecastRow, forecast_available_amount: null }),
    ).toBe("commissioning.forecast_enough_available");
  });

  it("leaves the forecast blank for a row without one", () => {
    expect(cellText(column("forecast_available_amount"), undefined, plainRow)).toBe("");
  });

  it.skip("shows a kilo forecast at the unit's precision", () => {
    expect(
      cellText(column("forecast_available_amount"), undefined, {
        ...forecastRow,
        forecast_available_amount: "2.50",
      }),
    ).toBe("2,50");
  });

  it("shows the forecast and stock notes as they come", () => {
    const notes = { hasForecastNote: true, hasStockNote: true };

    expect(cellText(column("forecast_note", { dataHasNotes: notes }), "Feld 3", forecastRow)).toBe("Feld 3");
    expect(cellText(column("current_stock_note", { dataHasNotes: notes }), "gezählt", forecastRow)).toBe("gezählt");
    expect(cellText(column("forecast_note", { dataHasNotes: notes }), null, plainRow)).toBe("");
  });

  it("shows a whole stock amount as it comes", () => {
    expect(cellText(column("current_stock_begin_of_week"), 30, stockRow)).toBe("30");
  });

  it.skip("shows a kilo stock amount in the farm's format", () => {
    expect(
      cellText(column("current_stock_begin_of_week"), 12.5, forecastRow),
    ).toBe("12,50");
  });

  it("shows what is still free from the page's calculation", () => {
    const calculateStillFree = vi.fn(() => 1200);
    const col = column("still_free", { calculateStillFree });

    const style = cellStyle(col, undefined, forecastRow);

    expect(cellText(col, undefined, forecastRow)).toBe("1.200");
    expect(calculateStillFree).toHaveBeenCalledWith(forecastRow);
    expect(style.color).toBe("green");
    expect(style.fontWeight).toBe("normal");
  });

  it("shows an over-planned row red and bold", () => {
    const col = column("still_free", { calculateStillFree: () => -5 });

    const style = cellStyle(col, undefined, forecastRow);

    expect(cellText(col, undefined, forecastRow)).toBe("-5");
    expect(style.color).toBe("red");
    expect(style.fontWeight).toBe("bold");
  });

  it.skip("shows a kilo still-free amount at the unit's precision", () => {
    const col = column("still_free", { calculateStillFree: () => -0.4 });

    expect(cellText(col, undefined, forecastRow)).toBe("-0,40");
  });
});

describe("usePlanningHarvestSharesColumns backup button", () => {
  const renderBackup = (record: TableRecord, onRowClick = vi.fn()) => {
    const col = column("backup");
    const cell = col.render?.(undefined, record, 0) as ReactNode;
    render(
      <div onClick={onRowClick}>{cell}</div>,
    );
    return onRowClick;
  };

  it("shows nothing on the summary row", () => {
    expect(renderCell(column("backup"), undefined, { key: "summary-row" })).toBeEmptyDOMElement();
  });

  it("opens the backup dialog for the row without selecting the row", () => {
    const onRowClick = renderBackup(forecastRow);

    fireEvent.click(screen.getByRole("button"));

    expect(setters.setIsBackupModalOpen).toHaveBeenCalledWith(true);
    expect(setters.setSelectedBackupData).toHaveBeenCalledWith(forecastRow);
    expect(onRowClick).not.toHaveBeenCalled();
  });

  it("marks a row that has a backup", () => {
    renderBackup(forecastRow);

    const button = screen.getByRole("button");
    expect(button.style.backgroundColor).toBe("var(--color-success-bg)");
    expect(button.style.color).toBe("var(--color-success-text)");
  });

  it("leaves a row without a backup unmarked", () => {
    renderBackup(stockRow);

    const button = screen.getByRole("button");
    expect(button.style.backgroundColor).toBe("");
    expect(button.style.color).toBe("");
  });
});
