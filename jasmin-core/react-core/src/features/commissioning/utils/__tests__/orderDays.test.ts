import type { TFunction } from "i18next";
import { describe, expect, it } from "vitest";
import { missingOrderDays, orderDayConfigs } from "../orderDays";

const days = orderDayConfigs(((key: string) => key) as unknown as TFunction);
const ALL_DAYS = {
  harvesting_day: 1,
  packing_day: 3,
  washing_day: 2,
  cleaning_day: 2,
};

describe("missingOrderDays", () => {
  it("names the days a new order lacks", () => {
    expect(
      missingOrderDays(
        days,
        { ...ALL_DAYS, washing_day: null, packing_day: null },
        null,
      ).map(({ field }) => field),
    ).toEqual(["washing_day", "packing_day"]);
  });

  it("finds none once every day is picked", () => {
    expect(missingOrderDays(days, ALL_DAYS, null)).toEqual([]);
  });

  it("finds none for an existing order, which keeps its own days", () => {
    expect(
      missingOrderDays(days, { ...ALL_DAYS, harvesting_day: null }, "order-1"),
    ).toEqual([]);
  });
});
