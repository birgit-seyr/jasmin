/**
 * The farm the waste documentation tests run against: its storages and
 * articles, and the waste recorded in week 41 and week 39 of 2026.
 */
import type { ShareArticle, Storage, Waste } from "@shared/api/generated/models";

export const COLD_STORE: Storage = { id: "st-cold", name: "Cold store", is_active: true };
export const ROOT_CELLAR: Storage = { id: "st-cellar", name: "Root cellar", is_active: true };
export const FARM_SHOP: Storage = { id: "st-shop", name: "Farm shop", is_active: true };
export const STORAGES = [COLD_STORE, ROOT_CELLAR, FARM_SHOP];

export const article = (name: string, unit: ShareArticle["default_movement_unit"]): ShareArticle => ({
  id: `sa-${name.toLowerCase()}`, name, default_movement_unit: unit, is_active: true,
});

export const CARROTS = article("Carrots", "KG");
export const LETTUCE = article("Lettuce", "PCS");
export const RADISHES = article("Radishes", "BUNCH");
export const POTATOES = article("Potatoes", "KG");
export const LEEKS = article("Leeks", "KG");
export const BEETROOT = article("Beetroot", "KG");
export const CHARD = article("Chard", "BUNCH");

/** A waste row as the list returns it, with its ``storage_<id>`` flags. */
export type WasteRow = Waste & Record<string, unknown>;
export type Payload = Record<string, unknown>;

/** A day of 2026: its ISO week and its backend day number (0 = Monday). */
export type Day = { week: number; day: number };
export const TUESDAY: Day = { week: 41, day: 1 };
export const WEDNESDAY: Day = { week: 41, day: 2 };
export const TUESDAY_WEEK_39: Day = { week: 39, day: 1 };

export const waste = (
  id: string,
  ofArticle: ShareArticle,
  storage: Storage,
  when: Day,
  fields: Partial<WasteRow> = {},
): WasteRow => ({
  id,
  year: 2026,
  delivery_week: when.week,
  day_number: when.day as Waste["day_number"],
  share_article: ofArticle.id!,
  share_article_name: ofArticle.name,
  unit: ofArticle.default_movement_unit,
  size: "M",
  amount: null,
  note: "",
  storage: storage.id!,
  created_by: null,
  // The list flags the storage a row is kept in among all active ones.
  ...Object.fromEntries(STORAGES.map((each) => [`storage_${each.id}`, each.id === storage.id])),
  ...fields,
});

// Tuesday of week 41: carrots and lettuce thrown away from the cold store,
// potatoes from the root cellar. Wednesday: radishes. Week 39: leeks.
export const CARROTS_WASTE = waste("waste-carrots", CARROTS, COLD_STORE, TUESDAY, {
  amount: "4.00", note: "Rotten at the bottom",
});
export const LETTUCE_WASTE = waste("waste-lettuce", LETTUCE, COLD_STORE, TUESDAY, { size: "L", amount: "12.00" });
export const POTATOES_WASTE = waste("waste-potatoes", POTATOES, ROOT_CELLAR, TUESDAY, {
  amount: "25.00", note: "Sprouted",
});
export const RADISHES_WASTE = waste("waste-radishes", RADISHES, COLD_STORE, WEDNESDAY, { amount: "3.00" });
export const LEEKS_WASTE = waste("waste-leeks", LEEKS, COLD_STORE, TUESDAY_WEEK_39, { amount: "7.00" });


/** An amount as the backend's two-decimal field returns it. */
export const decimal = (value: unknown) =>
  value === null || value === undefined || value === "" ? null : Number(value).toFixed(2);

/** The fields every waste saved from the frozen day in the cold store carries. */
export const TUESDAY_IN_COLD_STORE = { storage: COLD_STORE.id, year: 2026, delivery_week: 41, day_number: 1 };
