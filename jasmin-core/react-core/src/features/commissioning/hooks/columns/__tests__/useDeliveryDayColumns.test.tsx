/**
 * useDeliveryDayColumns: the planning grid's (delivery day × variation)
 * columns in the day-major and the "days together" layout, per planning mode
 * (basic, tours, stations), their amount cells and forecast highlight, and the
 * per-day planned and harvested totals.
 */
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  baseParams,
  carrotRow,
  friday,
  small,
  subscriberCounts,
  tuesday,
} from "./useDeliveryDayColumns.fixtures";
import {
  cellText,
  columnIds,
  findColumn,
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

import { useDeliveryDayColumns } from "../useDeliveryDayColumns";

type Params = Parameters<typeof useDeliveryDayColumns>[0];

const build = (overrides: Partial<Params> = {}): Column[] =>
  renderHook(() => useDeliveryDayColumns({ ...baseParams, ...overrides }))
    .result.current.deliveryDayColumns;

const cellKey = (variationId: string, tier = "") =>
  `day_day-tue_variation_${variationId}${tier}`;

beforeEach(() => {
  tenantState.settings = {};
});

describe("useDeliveryDayColumns day by day", () => {
  it("groups the columns by delivery day, titled by the day", () => {
    const columns = build();

    expect(columnIds(columns)).toEqual(["day_day-tue", "day_day-fri"]);
    expect(columns.map((column) => column.title)).toEqual(["Di", "Fr"]);
    expect(columns.every((c) => c.className === "column-group-start")).toBe(true);
  });

  it("gives each day a column per variation, then its planned and harvested totals", () => {
    const [tue] = build();

    expect(columnIds(tue.children ?? [])).toEqual([
      "day_day-tue_variation_var-s",
      "day_day-tue_variation_var-l",
      "day_day-tue_planned_amount",
      "day_day-tue_harvested",
    ]);
  });

  it("titles each variation column by the variation's size", () => {
    const [tue] = build();
    const [smallColumn, largeColumn] = tue.children ?? [];

    expect(smallColumn.title).toBe("commissioning.S");
    expect(largeColumn.title).toBe("commissioning.L");
  });

  it("starts the day's first column a group and each further variation a new variation", () => {
    const [smallColumn, largeColumn, planned] = build()[0].children ?? [];

    expect(smallColumn.className).toBe("column-group-start");
    expect(largeColumn.className).toBe("column-variation-start");
    expect(planned.className).toBeUndefined();
  });

  it("takes amounts per share at two decimals", () => {
    const column = findColumn(build(), cellKey("var-s"));

    expect(column.inputType).toBe("positive_decimal2");
    expect(column.children).toBeUndefined();
  });

  it("builds no day without delivery days, and empty days without variations", () => {
    expect(build({ shareDeliveryDays: [] })).toEqual([]);
    expect(
      columnIds(build({ shareTypeVariations: [] })[0].children ?? []),
    ).toEqual(["day_day-tue_planned_amount", "day_day-tue_harvested"]);
  });
});

describe("useDeliveryDayColumns tours and stations", () => {
  it("splits a variation into the day's tours by tour number", () => {
    const column = findColumn(build({ planningMode: "tours", shareDeliveryDays: [tuesday] }), cellKey("var-s"));

    expect((column.children ?? []).map((c) => c.title)).toEqual(["T1", "T3"]);
    expect(columnIds(column.children ?? [])).toEqual([
      cellKey("var-s", "_tour_1"),
      cellKey("var-s", "_tour_3"),
    ]);
  });

  it("splits a variation into the day's stations by short name", () => {
    const column = findColumn(
      build({ planningMode: "stations", shareDeliveryDays: [tuesday] }),
      cellKey("var-s"),
    );

    expect((column.children ?? []).map((c) => c.title)).toEqual(["Hof", "Markt"]);
    expect(columnIds(column.children ?? [])).toEqual([
      cellKey("var-s", "_station_st-hof"),
      cellKey("var-s", "_station_st-markt"),
    ]);
    expect(column.children?.[0].width).toBe("8em");
  });

  it("plans a day without tours or stations as a whole day", () => {
    for (const planningMode of ["tours", "stations"]) {
      const [fri] = build({
        planningMode,
        shareDeliveryDays: [friday],
        shareTypeVariations: [small],
      });
      const [smallColumn] = fri.children ?? [];
      expect(smallColumn.children).toBeUndefined();
      expect(smallColumn.dataIndex).toBe("day_day-fri_variation_var-s");
      expect(smallColumn.title).toBe("commissioning.S");
      expect(smallColumn.inputType).toBe("positive_decimal2");
    }
  });

  it("builds a tour-planning week holding a day whose stations carry no tour number", () => {
    for (const used_tours of [null, []]) {
      const columns = build({
        planningMode: "tours",
        shareDeliveryDays: [tuesday, { ...friday, used_tours } as typeof friday],
      });

      const [smallColumn, largeColumn] = findColumn(columns, "day_day-fri").children ?? [];
      expect(smallColumn.children).toBeUndefined();
      expect(largeColumn.children).toBeUndefined();
      expect(largeColumn.className).toBe("column-variation-start");
      expect(
        findColumn(columns, "day_day-tue_variation_var-l").children,
      ).toHaveLength(2);
    }
  });

  it("starts the first tour of a further variation a new variation", () => {
    const [, largeColumn] = build({ planningMode: "tours", shareDeliveryDays: [tuesday] })[0].children ?? [];

    expect(largeColumn.className).toBe("column-variation-start");
    expect(largeColumn.children?.[0].className).toBe("column-variation-start");
    expect(largeColumn.children?.[1].className).toBeUndefined();
  });

  it("starts the first tour of the day a group", () => {
    const [smallColumn] = build({ planningMode: "tours", shareDeliveryDays: [tuesday] })[0].children ?? [];

    expect(smallColumn.className).toBe("column-group-start");
    expect(smallColumn.children?.[0].className).toBe("column-group-start");
  });
});

describe("useDeliveryDayColumns days together", () => {
  it("groups the columns by variation, titled by its size", () => {
    const columns = build({ showDaysTogether: true });

    expect(columnIds(columns)).toEqual(["variation_var-s", "variation_var-l"]);
    expect(columns.map((column) => column.title)).toEqual([
      "commissioning.S",
      "commissioning.L",
    ]);
  });

  it("starts each variation a group and every further one a new variation", () => {
    const [first, second] = build({ showDaysTogether: true });

    expect(first.className).toBe("column-group-start");
    expect(second.className).toBe("column-group-start column-variation-start");
  });

  it("gives each variation a column per day, titled by the day, without totals", () => {
    const [first] = build({ showDaysTogether: true });

    expect(columnIds(first.children ?? [])).toEqual([
      "day_day-tue_variation_var-s",
      "day_day-fri_variation_var-s",
    ]);
    expect((first.children ?? []).map((c) => c.title)).toEqual(["Di", "Fr"]);
    expect(first.children?.[0].className).toBe("column-group-start");
    expect(first.children?.[0].inputType).toBe("positive_decimal2");
  });

  it("splits each day into its tours", () => {
    const [first] = build({ showDaysTogether: true, planningMode: "tours" });
    const [tue] = first.children ?? [];

    expect(tue.title).toBe("Di");
    expect((tue.children ?? []).map((c) => c.title)).toEqual(["T1", "T3"]);
    expect(tue.children?.[0].className).toBe("column-group-start");
    // Friday runs no tour, so it is planned as a whole day.
    expect(first.children?.[1].children).toBeUndefined();
    expect(first.children?.[1].title).toBe("Fr");
    expect(first.children?.[1].dataIndex).toBe("day_day-fri_variation_var-s");
  });

  it("splits each day into its stations", () => {
    const [first] = build({ showDaysTogether: true, planningMode: "stations" });

    expect(
      (first.children?.[0].children ?? []).map((c) => c.title),
    ).toEqual(["Hof", "Markt"]);
  });
});

describe("useDeliveryDayColumns amount cells", () => {
  it("shows a kilo amount at two decimals in the farm's format", () => {
    const column = findColumn(build(), cellKey("var-l"));

    expect(cellText(column, 0.75, carrotRow)).toBe("0,75");
    expect(cellText(column, "1234.5", carrotRow)).toBe("1.234,50");
  });

  it("shows a piece amount at one decimal", () => {
    const column = findColumn(build(), cellKey("var-l"));

    expect(cellText(column, 2, { key: "r", unit: "PCS" })).toBe("2,0");
  });

  it("shows an amount without a unit at two decimals", () => {
    const column = findColumn(build(), cellKey("var-l"));

    expect(cellText(column, 2, { key: "r" })).toBe("2,00");
  });

  it("follows the farm's number locale", () => {
    tenantState.settings = { number_locale: "en-US" };
    const column = findColumn(build(), cellKey("var-l"));

    expect(cellText(column, 1234.5, carrotRow)).toBe("1,234.50");
  });

  it.each([0, "0.00", null, undefined, "", "n/a"])(
    "leaves an amount of %s blank",
    (value) => {
      const column = findColumn(build(), cellKey("var-s"));

      expect(renderCell(column, value, carrotRow)).toBeEmptyDOMElement();
    },
  );

  it("renders the same cell in tour, station and days-together leaves", () => {
    const leaves = [
      findColumn(build({ planningMode: "tours", shareDeliveryDays: [tuesday] }), cellKey("var-s", "_tour_3")),
      findColumn(
        build({ planningMode: "stations", shareDeliveryDays: [tuesday] }),
        cellKey("var-s", "_station_st-hof"),
      ),
      findColumn(build({ showDaysTogether: true }), cellKey("var-s")),
    ];

    for (const leaf of leaves) {
      expect(cellText(leaf, 0.25, carrotRow)).toBe("0,25");
      expect(leaf.inputType).toBe("positive_decimal2");
    }
  });

  it("highlights an empty cell of a variation the forecast names", () => {
    const column = findColumn(
      build({ showForecastClassification: true }),
      cellKey("var-l"),
    );

    const cell = renderCell(column, 0, carrotRow).firstElementChild as HTMLElement;

    expect(cell.textContent).toBe("");
    expect(cell).toHaveClass("planning-variation-cell-highlight");
  });

  it("does not highlight a filled cell of a forecast variation", () => {
    const column = findColumn(
      build({ showForecastClassification: true }),
      cellKey("var-l"),
    );

    const cell = renderCell(column, 0.75, carrotRow).firstElementChild as HTMLElement;

    expect(cell.textContent).toBe("0,75");
    expect(cell).toHaveClass("planning-variation-cell");
    expect(cell).not.toHaveClass("planning-variation-cell-highlight");
  });

  it("does not highlight a variation the forecast leaves out", () => {
    const column = findColumn(
      build({ showForecastClassification: true }),
      cellKey("var-s"),
    );

    expect(renderCell(column, 0, carrotRow)).toBeEmptyDOMElement();
  });

  it("does not highlight a row without a forecast", () => {
    const column = findColumn(
      build({ showForecastClassification: true }),
      cellKey("var-l"),
    );

    expect(renderCell(column, 0, { key: "r", unit: "KG" })).toBeEmptyDOMElement();
  });

  it("does not highlight while the forecast classification is off", () => {
    const column = findColumn(build(), cellKey("var-l"));

    expect(renderCell(column, 0, carrotRow)).toBeEmptyDOMElement();
  });

  it("highlights a forecast variation's empty tour leaf too", () => {
    const column = findColumn(
      build({ showForecastClassification: true, planningMode: "tours", shareDeliveryDays: [tuesday] }),
      `day_day-tue_variation_var-l_tour_1`,
    );

    const cell = renderCell(column, null, carrotRow).firstElementChild as HTMLElement;
    expect(cell).toHaveClass("planning-variation-cell-highlight");
  });
});

describe("useDeliveryDayColumns day totals", () => {
  const planned = (overrides: Partial<Params> = {}) =>
    findColumn(build(overrides), "day_day-tue_planned_amount");
  const harvested = (overrides: Partial<Params> = {}) =>
    findColumn(build(overrides), "day_day-tue_harvested");

  it("locks both totals and titles them", () => {
    expect(isDisabled(planned(), carrotRow)).toBe(true);
    expect(isDisabled(harvested(), carrotRow)).toBe(true);
    expect(titleText(planned().title)).toBe("commissioning.total_planned_amount");
    expect(titleText(harvested().title)).toBe(
      "commissioning.available_amount_harvest",
    );
  });

  it("hides both totals unless the detailed columns are on", () => {
    expect(planned().hidden).toBe(false);
    expect(harvested().hidden).toBe(false);
    expect(planned({ showDetailedColumns: false }).hidden).toBe(true);
    expect(harvested({ showDetailedColumns: false }).hidden).toBe(true);
  });

  it("totals the day live from the per-share amounts times the subscribers", () => {
    const column = planned({ shareTypeVariationAmountsSummary: subscriberCounts });

    // 13 × 0.50 + 2 × 0.75
    expect(cellText(column, 12, carrotRow)).toBe("8,00");
  });

  it("totals the day per tour in tour planning", () => {
    const column = planned({
      planningMode: "tours", shareDeliveryDays: [tuesday],
      shareTypeVariationAmountsSummary: subscriberCounts,
    });

    // 10 × 0.5 + 4 × 0.25
    expect(cellText(column, 12, carrotRow)).toBe("6,00");
  });

  it("totals the day per station in station planning", () => {
    const column = planned({
      planningMode: "stations", shareDeliveryDays: [tuesday],
      shareTypeVariationAmountsSummary: subscriberCounts,
    });

    // 8 × 0.5 + 5 × 0
    expect(cellText(column, 12, carrotRow)).toBe("4,00");
  });

  it("leaves the total blank when nothing is planned", () => {
    const column = planned({ shareTypeVariationAmountsSummary: subscriberCounts });

    expect(cellText(column, 12, { key: "r", unit: "KG" })).toBe("");
  });

  it("shows the saved total without subscriber counts", () => {
    const column = planned();

    expect(cellText(column, 1200, carrotRow)).toBe("1.200,00");
    expect(cellText(column, null, carrotRow)).toBe("");
    expect(cellText(column, "n/a", carrotRow)).toBe("");
  });

  it("shows a kilo total at the unit's precision", () => {
    const column = planned({ shareTypeVariationAmountsSummary: subscriberCounts });

    // 13 × 0.5 kg = 6.5 kg
    expect(
      cellText(column, 0, { key: "r", unit: "KG", [cellKey("var-s")]: 0.5 }),
    ).toBe("6,50");
  });

  it("shows a piece total at one decimal", () => {
    const column = planned({ shareTypeVariationAmountsSummary: subscriberCounts });

    // 13 × 2 pieces
    expect(
      cellText(column, 0, { key: "r", unit: "PCS", [cellKey("var-s")]: 2 }),
    ).toBe("26,0");
  });

  it("totals a whole-day planned day in tour planning", () => {
    const column = findColumn(
      build({
        planningMode: "tours",
        shareDeliveryDays: [friday],
        shareTypeVariationAmountsSummary: { "day_day-fri_variation_var-s": "6" },
      }),
      "day_day-fri_planned_amount",
    );

    // 6 × 0.5 kg
    expect(
      cellText(column, 0, { key: "r", unit: "KG", "day_day-fri_variation_var-s": 0.5 }),
    ).toBe("3,00");
  });

  it("shows the harvested amount as the row carries it", () => {
    const column = harvested();

    const cell = renderCell(column, "4,5 kg", carrotRow);
    expect(cell.textContent).toBe("4,5 kg");
    expect(cell.firstElementChild).toHaveClass("read-only-amounts-harvest");
  });

  it("gives every day its own totals", () => {
    const columns = build({ shareTypeVariationAmountsSummary: subscriberCounts });

    expect(
      cellText(findColumn(columns, "day_day-fri_planned_amount"), 0, carrotRow),
    ).toBe("");
  });
});
