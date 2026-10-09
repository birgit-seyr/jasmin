import { renderHook } from "@testing-library/react";
import type { TFunction } from "i18next";
import { describe, expect, it } from "vitest";

import { usePlanningSummaryData } from "../usePlanningSummaryData";
import { large, tuesday } from "../columns/__tests__/useDeliveryDayColumns.fixtures";

const cell = "day_day-tue_variation_var-l";

const sumsFor = (data: Record<string, unknown>[]) =>
  renderHook(() =>
    usePlanningSummaryData({
      shareDeliveryDays: [tuesday],
      shareTypeVariations: [large],
      planningMode: "basic",
      data: data.map((row, index) => ({ key: `row-${index}`, ...row })),
      vegetables_and_fruits: [],
      shareTypeVariationAmounts: null,
      t: ((key: string) => key) as unknown as TFunction,
      currencySymbol: "€",
      historicalAverages: null,
    }),
  ).result.current.dayVariationSums[cell];

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
