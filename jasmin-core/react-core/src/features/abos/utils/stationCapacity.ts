/**
 * THE single fullness computation for delivery-station-days, shared by every
 * capacity display (NewSubscriptionModal tag/flag, Abos row greying,
 * WaitingListAbos). All consumers must fetch ``capacity_by_week`` with the
 * SAME wide window (``CAPACITY_WINDOW_PARAMS``) so week keys are always
 * present for any realistic term — a narrower, differently-anchored fetch is
 * exactly what made the modal and the Abos table disagree.
 *
 * Semantics: a station-day is FULL for a term when ANY term week has
 * ``free <= 0``. Weeks missing from the window read as available — the
 * backend create/confirm capacity check stays the authority (it 409s with
 * ``delivery_station.over_capacity``).
 *
 * NOTE: capacity counts HARVEST boxes only (backend `_CAPACITY_SHARE_OPTIONS`)
 * — add-on shares (chicken, honey, bread, ...) ride along in the base box and
 * neither consume nor see capacity.
 */

import dayjs from "dayjs";
import type { CapacityWeekEntry } from "@shared/api/generated/models";

// Re-exported under the historical name: the shape now comes from the
// generated model (the backend schema types capacity_by_week precisely), so
// a backend rename of occupied/free breaks compilation here instead of
// silently zeroing the fullness math.
export type { CapacityWeekEntry };

export interface StationDayTermCapacity {
  /** DSD-wide capacity (null = unlimited). */
  total: number | null;
  /** Tightest week's free slots across the term (null when unknown). */
  minFree: number | null;
  /** Busiest week's occupancy across the term (the binding constraint —
   * Abos renders it as "peak/total"). */
  peakOccupied: number;
  /** Week key ("<iso-year>-<iso-week>") of the busiest week, null when no
   * term week carried data. */
  peakWeekKey: string | null;
  /** True when any term week has zero free slots. */
  isFull: boolean;
}

/** Wide fixed capacity window: ISO week 1 of the current ISO week-year, two
 * years ahead — matches every consumer so the same DSD always carries the same
 * week keys. Anchored on ``isoWeekYear`` (NOT the calendar ``year``) because the
 * week keys use isoWeekYear: around Jan 1 the current ISO week can belong to the
 * previous ISO year (e.g. 2027-01-01 is 2026-W53), and a calendar-year anchor
 * would start the window at 2027-W1 and drop that current week. */
export function capacityWindowParams(): {
  year: number;
  delivery_week: number;
  num_weeks: number;
} {
  return { year: dayjs().isoWeekYear(), delivery_week: 1, num_weeks: 104 };
}

/** Share options that CONSUME station capacity (mirror of the backend
 * `_CAPACITY_SHARE_OPTIONS`; note HARVEST_SHARE_FRUIT is the stored value of
 * the fruits-only option). Add-on variations (chicken, honey, bread, ...)
 * neither consume nor display capacity — never offer them a waiting_list. */
export const CAPACITY_SHARE_OPTIONS: readonly string[] = [
  "HARVEST_SHARE",
  "HARVEST_SHARE_FRUIT",
];

export function stationDayTermCapacity(
  capacity: number | null | undefined,
  capacityByWeek: Record<string, CapacityWeekEntry> | null | undefined,
  weekKeys: readonly string[],
  // Shares the order needs. ``isFull`` is quantity-aware: the term is full when
  // the tightest week can't fit ``quantity`` more shares — matching the backend
  // gate (peak + quantity > capacity), not just "zero free". A quantity=3 order
  // into a week with 2 free must waiting_list, exactly as the backend enforces.
  quantity: number = 1,
): StationDayTermCapacity {
  const total = capacity ?? null;
  let minFree: number | null = null;
  let peakOccupied = 0;
  let peakWeekKey: string | null = null;
  if (capacityByWeek) {
    for (const key of weekKeys) {
      const week = capacityByWeek[key];
      if (!week) continue;
      if (week.occupied > peakOccupied || peakWeekKey == null) {
        peakOccupied = Math.max(peakOccupied, week.occupied);
        if (week.occupied >= peakOccupied) peakWeekKey = key;
      }
      if (week.free == null) continue;
      minFree = minFree == null ? week.free : Math.min(minFree, week.free);
    }
  }
  const needed = quantity > 0 ? quantity : 1;
  const isFull = minFree != null && minFree < needed;
  return { total, minFree, peakOccupied, peakWeekKey, isFull };
}

/** The fullness evaluator is shape-generic — capacity + per-week
 * ``{occupied, free}`` → peak/isFull for a term — so the SAME function serves
 * the farm-wide ``ShareTypeVariation`` production cap. Aliased for call-site
 * clarity; this is THE one evaluator every capacity display (station-day AND
 * variation, in the modal, the abos select, and the office overview) reads. */
export const termCapacity = stationDayTermCapacity;
export type TermCapacity = StationDayTermCapacity;

/** ISO week keys ("<iso-year>-<iso-week>") spanning ``[from, until]`` inclusive,
 * matching the keys in ``capacity_by_week``. Open-ended terms (invalid/absent
 * ``until``) fall back to the fetched-window depth (104 weeks) from ``from`` —
 * so a full week further than a year out is still seen (the backend's peak is
 * unbounded; weeks past the fetched window simply have no key and read as free).
 * Shared by the station-day and variation option builders so the term→weeks
 * expansion can't drift between the two axes. */
export function termWeekKeys(
  from: dayjs.Dayjs,
  until: dayjs.Dayjs | null | undefined,
): string[] {
  const keys: string[] = [];
  const end = until && until.isValid() ? until : from.add(104, "week");
  let cursor = from.startOf("isoWeek");
  while (cursor.isSameOrBefore(end, "day")) {
    keys.push(`${cursor.isoWeekYear()}-${cursor.isoWeek()}`);
    cursor = cursor.add(1, "week");
  }
  return keys;
}

/** Forward-looking capacity-floor window: current ISO week, 156 weeks ahead.
 * Used when the question is "how low may the office set capacity?" — the
 * floor is the busiest CURRENT-OR-FUTURE week's occupancy (mirrors the
 * backend validate_capacity / peak_occupied_from_week contract; past weeks
 * must not inflate the floor). The horizon is wide (3 years) so the preview
 * can't undershoot the backend's UNBOUNDED floor for a far-future booking. */
export function capacityFloorParams(): {
  year: number;
  delivery_week: number;
  num_weeks: number;
} {
  const now = dayjs();
  return {
    year: now.isoWeekYear(),
    delivery_week: now.isoWeek(),
    num_weeks: 104,
  };
}

/** Week keys matching capacityFloorParams() — current ISO week forward. */
export function capacityFloorWeekKeys(): string[] {
  const { num_weeks } = capacityFloorParams();
  const keys: string[] = [];
  let cursor = dayjs().startOf("isoWeek");
  for (let i = 0; i < num_weeks; i += 1) {
    keys.push(`${cursor.isoWeekYear()}-${cursor.isoWeek()}`);
    cursor = cursor.add(1, "week");
  }
  return keys;
}

/** "2026-30" -> "30/2026" for user-facing week labels. */
export function formatWeekKey(weekKey: string): string {
  const [year, week] = weekKey.split("-");
  return `${week}/${year}`;
}
