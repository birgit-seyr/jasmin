import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import type { DeliveryDay } from "../useDeliveryDayColumns";
import type { ShareTypeVariationOption } from "../../useShareTypeVariations";

/** Tuesday runs tours 1 and 3 and serves two stations. */
export const tuesday = {
  id: "day-tue",
  value: "day-tue",
  label: "Di",
  day_number: 2,
  valid_from: "2026-01-05",
  used_tours: [1, 3],
  delivery_stations: [
    { id: "st-hof", short_name: "Hof", tour_number: 1, stop_order: 1 },
    { id: "st-markt", short_name: "Markt", tour_number: 3, stop_order: 1 },
  ],
} as unknown as DeliveryDay;

/** Friday runs no tour and serves no station yet. */
export const friday = {
  id: "day-fri",
  value: "day-fri",
  label: "Fr",
  day_number: 5,
  valid_from: "2026-01-05",
} as unknown as DeliveryDay;

export const small = {
  id: "var-s",
  value: "var-s",
  label: "S",
  size: "S",
  valid_from: "2026-01-05",
} as unknown as ShareTypeVariationOption;

export const large = {
  id: "var-l",
  value: "var-l",
  label: "L",
  size: "L",
  valid_from: "2026-01-05",
} as unknown as ShareTypeVariationOption;

export const baseParams = {
  shareDeliveryDays: [tuesday, friday],
  shareTypeVariations: [small, large],
  showDaysTogether: false,
  showDetailedColumns: true,
  planningMode: "basic",
  showForecastClassification: false,
};

/** A kilo planning row: 0.5 kg per small share and 0.75 kg per large share on Tuesday. */
export const carrotRow: TableRecord = {
  key: "row-carrot",
  unit: "KG",
  forecast_share_type_variation_ids: ["var-l"],
  "day_day-tue_variation_var-s": "0.50",
  "day_day-tue_variation_var-l": 0.75,
  "day_day-tue_variation_var-s_tour_1": 0.5,
  "day_day-tue_variation_var-s_tour_3": 0.25,
  "day_day-tue_variation_var-s_station_st-hof": 0.5,
  "day_day-tue_variation_var-s_station_st-markt": 0,
  "day_day-tue_planned_amount": 12,
  "day_day-tue_harvested": 0,
};

/** Subscribers per (day, variation[, tour|station]) cell. */
export const subscriberCounts: Record<string, string> = {
  "day_day-tue_variation_var-s": "13",
  "day_day-tue_variation_var-l": "2",
  "day_day-tue_variation_var-s_tour_1": "10",
  "day_day-tue_variation_var-s_tour_3": "4",
  "day_day-tue_variation_var-s_station_st-hof": "8",
  "day_day-tue_variation_var-s_station_st-markt": "5",
};
