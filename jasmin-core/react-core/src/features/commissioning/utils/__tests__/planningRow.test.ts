import { describe, expect, it } from "vitest";

import type { ShareArticle } from "@shared/api/generated/models";

import {
  articlePriceField,
  articleWeightField,
  forecastAmountInRowUnit,
  kgPerRowUnit,
  pricePerRowUnit,
  planningRowForecastUnit,
  planningRowUnit,
} from "../planningRow";

const article = {
  kg_per_piece_S: "0.100",
  kg_per_piece_M: "0.200",
  kg_per_piece_L: "0.300",
  kg_per_bunch_S: "0.400",
  kg_per_bunch_M: "0.500",
  kg_per_bunch_L: "0.600",
};

describe("planningRowUnit", () => {
  it("reads the row's unit", () => {
    expect(planningRowUnit({ key: "r", unit: "PCS" })).toBe("PCS");
  });

  it("is undefined on a row without a unit", () => {
    expect(planningRowUnit({ key: "r" })).toBeUndefined();
    expect(planningRowUnit({ key: "r", unit: null })).toBeUndefined();
  });
});

describe("planningRowForecastUnit", () => {
  it("prefers the forecast's unit and falls back to the row's", () => {
    expect(
      planningRowForecastUnit({ key: "r", unit: "KG", forecast_unit: "PCS" }),
    ).toBe("PCS");
    expect(
      planningRowForecastUnit({ key: "r", unit: "KG", forecast_unit: null }),
    ).toBe("KG");
  });
});

describe("forecastAmountInRowUnit", () => {
  it("counts a forecast in the row's unit", () => {
    expect(
      forecastAmountInRowUnit({
        key: "r",
        unit: "KG",
        forecast_unit: "KG",
        forecast_available_amount: "40.00",
      }),
    ).toBe(40);
  });

  it("leaves out a forecast in another unit", () => {
    expect(
      forecastAmountInRowUnit({
        key: "r",
        unit: "KG",
        forecast_unit: "PCS",
        forecast_available_amount: "40.00",
      }),
    ).toBe(0);
  });

  it("is zero for a row without a forecast", () => {
    expect(
      forecastAmountInRowUnit({
        key: "r",
        unit: "KG",
        forecast_unit: null,
        forecast_available_amount: null,
      }),
    ).toBe(0);
  });
});

describe("kgPerRowUnit", () => {
  it("weighs a kilo as one kilo", () => {
    expect(kgPerRowUnit({ key: "r", unit: "KG", size: "M", ...article })).toBe(1);
  });

  it.each([
    ["PCS", "S", 0.1],
    ["PCS", "M", 0.2],
    ["PCS", "L", 0.3],
    ["BUNCH", "S", 0.4],
    ["BUNCH", "M", 0.5],
    ["BUNCH", "L", 0.6],
  ])("weighs a %s of size %s by the article's weight", (unit, size, kg) => {
    expect(kgPerRowUnit({ key: "r", unit, size, ...article })).toBe(kg);
  });

  it("prefers the row's own weight over the article's", () => {
    expect(
      kgPerRowUnit({
        key: "r",
        unit: "BUNCH",
        size: "M",
        kg_per_piece: "0.750",
        ...article,
      }),
    ).toBe(0.75);
  });

  it("knows no weight without an article weight, a size or a weighable unit", () => {
    expect(kgPerRowUnit({ key: "r", unit: "PCS", size: "M" })).toBe(0);
    expect(kgPerRowUnit({ key: "r", unit: "PCS", ...article })).toBe(0);
    expect(kgPerRowUnit({ key: "r", unit: "L", size: "M", ...article })).toBe(0);
  });
});

describe("articlePriceField", () => {
  it.each([
    ["KG", "net_price_for_boxes_kg"],
    ["PCS", "net_price_for_boxes_pieces"],
    ["BUNCH", "net_price_for_boxes_bunch"],
  ])("prices a %s by the article's %s", (unit, field) => {
    expect(articlePriceField(unit)).toBe(field);
  });

  it("prices no other unit", () => {
    for (const unit of ["L", "G", "PIECES", "kg", undefined]) {
      expect(articlePriceField(unit)).toBeUndefined();
    }
  });
});

describe("articleWeightField", () => {
  it("weighs a piece and a bunch by the size's field", () => {
    expect(articleWeightField("PCS", "S")).toBe("kg_per_piece_S");
    expect(articleWeightField("BUNCH", "L")).toBe("kg_per_bunch_L");
  });

  it("has no weight field for kilos, other units or an unknown size", () => {
    expect(articleWeightField("KG", "M")).toBeUndefined();
    expect(articleWeightField("L", "M")).toBeUndefined();
    expect(articleWeightField("PIECES", "M")).toBeUndefined();
    expect(articleWeightField("PCS", "XL")).toBeUndefined();
    expect(articleWeightField("PCS", undefined)).toBeUndefined();
  });
});

describe("pricePerRowUnit", () => {
  const pricedArticle: ShareArticle = {
    name: "Carrots",
    default_movement_unit: "KG",
    net_price_for_boxes_kg: "2.50",
    net_price_for_boxes_pieces: "0.80",
    net_price_for_boxes_bunch: "1.20",
  };
  const unpricedArticle: ShareArticle = { name: "Dill", default_movement_unit: "BUNCH" };

  it.each([
    ["KG", 2.5],
    ["PCS", 0.8],
    ["BUNCH", 1.2],
  ])("prices a %s by the article's net box price", (unit, price) => {
    expect(pricePerRowUnit({ key: "r", unit }, pricedArticle)).toBe(price);
  });

  it("prefers the row's own price over the article's", () => {
    expect(
      pricePerRowUnit({ key: "r", unit: "KG", price_per_unit: "3.10" }, pricedArticle),
    ).toBe(3.1);
  });

  it("knows no price without an article, a priced unit or an article price", () => {
    expect(pricePerRowUnit({ key: "r", unit: "KG" }, undefined)).toBe(0);
    expect(pricePerRowUnit({ key: "r", unit: "L" }, pricedArticle)).toBe(0);
    expect(pricePerRowUnit({ key: "r", unit: "BUNCH" }, unpricedArticle)).toBe(0);
  });
});
