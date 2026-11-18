import dayjs from "dayjs";

import type {
  DayNumberEnum,
  ShareArticle,
  Storage,
  StorageLoggingEntry,
  TheoreticalHarvest,
} from "@shared/api/generated/models";
import { makeShareArticle, makeStorage } from "@/test/modelFixtures";

export const CELLAR: Storage = makeStorage({ id: "storage-cellar", name: "Cellar", is_active: true });
export const COLD_ROOM: Storage = makeStorage({ id: "storage-cold-room", name: "Cold room", is_active: true });

export const CARROTS: ShareArticle = makeShareArticle({ id: "sa-carrots", name: "Carrots", default_movement_unit: "KG" });
export const LEEK: ShareArticle = makeShareArticle({ id: "sa-leek", name: "Leek", default_movement_unit: "PCS" });

/** The ISO year, week and backend day number (0 = Monday) of a date. */
function isoDay(isoDate: string) {
  const date = dayjs(isoDate);
  return {
    year: date.isoWeekYear(),
    delivery_week: date.isoWeek(),
    day_number: (date.isoWeekday() - 1) as DayNumberEnum,
  };
}

/** One ledger row as the backend reports it: the movement's delta and the
 *  balance of its article in this storage after it. */
export function movement(
  id: string,
  type: string,
  isoDate: string,
  article: ShareArticle,
  amount: number,
  runningBalance: number,
  storage: Storage = CELLAR,
): StorageLoggingEntry {
  return {
    id,
    date: `${isoDate}T12:00:00+02:00`,
    type,
    share_article: article.id!,
    share_article_name: article.name,
    amount,
    unit: article.default_movement_unit,
    size: "M",
    ...isoDay(isoDate),
    storage_name: storage.name,
    running_balance: runningBalance,
  };
}

// The cellar's ledger, oldest first. Carrots: harvested, a zero-amount waste
// booking, packed into shares, counted (a correction of -2.5) and sold to a
// reseller beyond what was in stock. Leek: bought in.
export const CELLAR_LEDGER: StorageLoggingEntry[] = [
  movement("mv-harvest", "HARVEST", "2026-09-28", CARROTS, 25, 25),
  movement("mv-purchase", "PURCHASE", "2026-09-29", LEEK, 40, 40),
  movement("mv-waste", "WASTE", "2026-09-30", CARROTS, 0, 25),
  movement("mv-shares", "SHARECONTENT", "2026-10-01", CARROTS, -10, 15),
  movement("mv-count", "INVENTORY", "2026-10-02", CARROTS, -2.5, 12.5),
  movement("mv-order", "ORDERCONTENT", "2026-10-05", CARROTS, -14, -1.5),
];

export const COLD_ROOM_LEDGER: StorageLoggingEntry[] = [
  movement("mv-cold-harvest", "HARVEST", "2026-09-30", LEEK, 8, 8, COLD_ROOM),
];

/** One theoretical amount; the four workflow sources share this shape. */
function theoretical(
  id: string,
  isoDate: string,
  article: ShareArticle,
  amount: string | null,
  links: Partial<Pick<TheoreticalHarvest, "share_content" | "order_content">> = {},
): TheoreticalHarvest {
  return {
    id,
    created_at: `${isoDate}T08:00:00Z`,
    created_by: null,
    forecast: null,
    for_order_content: Boolean(links.order_content),
    ...isoDay(isoDate),
    amount,
    unit: article.default_movement_unit,
    size: "M",
    share_article: article.id!,
    share_article_name: article.name,
    storage: CELLAR.id!,
    share_content: null,
    order_content: null,
    ...links,
  };
}

export const HARVESTS: TheoreticalHarvest[] = [
  theoretical("th-carrots", "2026-09-29", CARROTS, "25.00", { share_content: "sc-1" }),
  theoretical("th-leek", "2026-10-05", LEEK, "40.00", { order_content: "oc-1" }),
  theoretical("th-zero", "2026-09-23", CARROTS, "0.00"),
  theoretical("th-open", "2026-09-17", CARROTS, null),
  theoretical("th-next-year", "2027-01-11", LEEK, "12.00"),
];
export const CLEAN_AMOUNTS = [theoretical("tc-carrots", "2026-09-30", CARROTS, "18.00")];
export const WASH_AMOUNTS = [theoretical("tw-carrots", "2026-10-01", CARROTS, "7.50")];
export const PURCHASE_AMOUNTS = [theoretical("tp-leek", "2026-10-06", LEEK, "30.00")];
