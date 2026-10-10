import { renderHook } from "@testing-library/react";
import type { TFunction } from "i18next";
import { describe, expect, it } from "vitest";

import { usePlanningSummaryData } from "../usePlanningSummaryData";
import type { ShareArticleOption } from "../useShareArticles";
import { large, tuesday } from "../columns/__tests__/useDeliveryDayColumns.fixtures";

const cell = "day_day-tue_variation_var-l";

const summaryFor = (
  data: Record<string, unknown>[],
  articles: ShareArticleOption[] = [],
) =>
  renderHook(() =>
    usePlanningSummaryData({
      shareDeliveryDays: [tuesday],
      shareTypeVariations: [large],
      planningMode: "basic",
      data: data.map((row, index) => ({ key: `row-${index}`, ...row })),
      vegetables_and_fruits: articles,
      shareTypeVariationAmounts: null,
      t: ((key: string) => key) as unknown as TFunction,
      currencySymbol: "€",
      historicalAverages: null,
    }),
  ).result.current;

const sumsFor = (data: Record<string, unknown>[]) =>
  summaryFor(data).dayVariationSums[cell];

const carrots: ShareArticleOption = {
  id: "carrots",
  value: "carrots",
  label: "Carrots",
  name: "Carrots",
  default_movement_unit: "KG",
  net_price_for_boxes_kg: "2.50",
  net_price_for_boxes_pieces: "0.80",
  net_price_for_boxes_bunch: "1.20",
};

const pricesFor = (data: Record<string, unknown>[]) =>
  summaryFor(data, [carrots]).dayVariationCounts[cell];

describe("usePlanningSummaryData kilo sums", () => {
  it("adds kilos as they are and weighs pieces and bunches by size", () => {
    expect(
      sumsFor([
        { unit: "KG", size: "M", [cell]: 2 },
        { unit: "PCS", size: "S", kg_per_piece_S: "0.100", [cell]: 3 },
        { unit: "PCS", size: "L", kg_per_piece_L: "0.300", [cell]: 1 },
        { unit: "BUNCH", size: "M", kg_per_bunch_M: "0.500", [cell]: 2 },
      ]),
    ).toBeCloseTo(2 + 0.3 + 0.3 + 1);
  });

  it("weighs by the row's own weight before the article's", () => {
    expect(
      sumsFor([
        {
          unit: "PCS",
          size: "M",
          kg_per_piece: "0.250",
          kg_per_piece_M: "0.200",
          [cell]: 4,
        },
      ]),
    ).toBe(1);
  });

  it("leaves out a row whose weight is unknown", () => {
    expect(sumsFor([{ unit: "BUNCH", size: "M", [cell]: 4 }])).toBe(0);
  });
});

describe("usePlanningSummaryData prices", () => {
  it("prices each unit by the article's net box price for it", () => {
    expect(
      pricesFor([
        { share_article: "carrots", unit: "KG", [cell]: 2 },
        { share_article: "carrots", unit: "PCS", [cell]: 5 },
        { share_article: "carrots", unit: "BUNCH", [cell]: 1 },
      ]),
    ).toBeCloseTo(2 * 2.5 + 5 * 0.8 + 1.2);
  });

  it("prices by the row's own price before the article's", () => {
    expect(
      pricesFor([
        { share_article: "carrots", unit: "KG", price_per_unit: "4.00", [cell]: 2 },
        { share_article: "unknown", unit: "KG", price_per_unit: "1.50", [cell]: 2 },
      ]),
    ).toBe(11);
  });

  it("leaves out a row without a known article or a priced unit", () => {
    expect(
      pricesFor([
        { share_article: "unknown", unit: "KG", [cell]: 2 },
        { share_article: "carrots", unit: "L", [cell]: 3 },
      ]),
    ).toBe(0);
  });
});
