/**
 * SINGLE SOURCE OF TRUTH for the planning grid's column / data-index key format.
 *
 * The planning + backup grids encode a (delivery-day × share-type-variation)
 * matrix into flat record keys that travel to and from the Django backend
 * verbatim. Historically every builder and reader hand-wrote these template
 * literals (`` `day_${d}_variation_${v}` ``, `` `backup_day_…` ``,
 * `` `amount_day_…` ``) and the parsers hand-rolled `startsWith`/`includes`
 * checks — so the format could (and did) drift between call sites. Build and
 * parse keys ONLY through these helpers; see docs/day-variation-columns-audit.md.
 *
 * Key grammar (day/variation ids are UUIDs → never contain `_`):
 *   [<prefix>]day_<dayId>_variation_<variationId>[ _tour_<n> | _station_<sid> ]
 *   [<prefix>]day_<dayId>_planned_amount        (per-day trailer leaf)
 *   [<prefix>]day_<dayId>_harvested             (per-day trailer leaf)
 *   amount_day_<dayId>[ _tour_<n> | _station_<sid> ]   (AmountShares, transposed)
 *   [<prefix>]variation_<variationId>           (day-less, day fixed by query)
 */

/** The three granularity tiers a day×variation cell can carry. */
export type ColumnKeyTier = "bare" | "tour" | "station";

export interface DayVariationKeyParts {
  dayId: string | number;
  variationId: string | number;
  /** Tour number for the `tours` planning mode. Mutually exclusive with `station`. */
  tour?: string | number | null;
  /** Delivery-station id for the `stations` planning mode. Mutually exclusive with `tour`. */
  station?: string | number | null;
  /** Namespace prefix, e.g. `"backup_"`. Defaults to none. */
  prefix?: string;
}

/**
 * Build `[<prefix>]day_<dayId>_variation_<variationId>[_tour_<n>|_station_<sid>]`.
 * Pass at most one of `tour` / `station` (they are the two non-basic tiers).
 */
export function dayVariationKey({
  dayId,
  variationId,
  tour,
  station,
  prefix = "",
}: DayVariationKeyParts): string {
  let key = `${prefix}day_${dayId}_variation_${variationId}`;
  if (tour !== undefined && tour !== null) key += `_tour_${tour}`;
  if (station !== undefined && station !== null) key += `_station_${station}`;
  return key;
}

/** Per-day "total planned amount" trailer leaf: `[<prefix>]day_<dayId>_planned_amount`. */
export function dayPlannedAmountKey(
  dayId: string | number,
  prefix = "",
): string {
  return `${prefix}day_${dayId}_planned_amount`;
}

/** Per-day "available harvested amount" trailer leaf: `[<prefix>]day_<dayId>_harvested`. */
export function dayHarvestedKey(dayId: string | number, prefix = ""): string {
  return `${prefix}day_${dayId}_harvested`;
}

export interface DayAmountKeyParts {
  dayId: string | number;
  tour?: string | number | null;
  station?: string | number | null;
}

/**
 * AmountShares' transposed key: `amount_day_<dayId>[_tour_<n>|_station_<sid>]`.
 * There is no `_variation_` segment — the variation is the table ROW there, so
 * the column encodes only the day (+ optional tour/station tier). The backend
 * emits exactly these keys on `variationDeliveryCountRow`.
 */
export function dayAmountKey({ dayId, tour, station }: DayAmountKeyParts): string {
  let key = `amount_day_${dayId}`;
  if (tour !== undefined && tour !== null) key += `_tour_${tour}`;
  if (station !== undefined && station !== null) key += `_station_${station}`;
  return key;
}

/** Day-less variation column key: `[<prefix>]variation_<variationId>`. */
export function variationColumnKey(
  variationId: string | number,
  prefix = "",
): string {
  return `${prefix}variation_${variationId}`;
}

/**
 * Long-term planner's per-variation amount key: `amount_<variationId>`. The
 * default-share-content backend reads every `amount_*` field as a
 * share_type_variation id (there is no day axis in the long-term planner), so
 * this is a DISTINCT format from `dayAmountKey`'s `amount_day_<dayId>…`.
 */
export function variationAmountKey(variationId: string | number): string {
  return `amount_${variationId}`;
}

export interface ParsedDayVariationKey {
  /** Everything before `day_` (e.g. `"backup_"`, or `""`). */
  prefix: string;
  dayId: string;
  variationId: string;
  tour?: string;
  station?: string;
  tier: ColumnKeyTier;
}

// Anchored so a stray `..._planned_amount` / `..._harvested` trailer does NOT
// masquerade as a variation cell. day/variation/station ids are UUIDs and tour
// is an integer — none contain `_`, so greedy `[^_]+` captures each segment
// exactly up to the next delimiter.
const DAY_VARIATION_RE =
  /^(.*?)day_([^_]+)_variation_([^_]+)(?:_tour_([^_]+)|_station_([^_]+))?$/;

/**
 * Parse a day×variation key into its parts, or return `null` if `key` is not
 * one (including the `_planned_amount` / `_harvested` trailer leaves, which are
 * day-scoped but carry no variation).
 */
export function parseDayVariationKey(key: string): ParsedDayVariationKey | null {
  const match = DAY_VARIATION_RE.exec(key);
  if (!match) return null;
  const [, prefix, dayId, variationId, tour, station] = match;
  return {
    prefix,
    dayId,
    variationId,
    tour,
    station,
    tier: tour !== undefined ? "tour" : station !== undefined ? "station" : "bare",
  };
}

/** Cheap predicate: is `key` any day×variation cell (any prefix, any tier)? */
export function isDayVariationKey(key: string): boolean {
  return DAY_VARIATION_RE.test(key);
}

/**
 * The key tier that a planning mode's editable cells live in:
 * `basic` → `bare`, `tours` → `tour`, `stations` → `station` (unknown → `bare`).
 * The single mapping between the mode selector and the key grammar, so the
 * "which keys belong to this mode" scans and the structural key builders agree.
 */
export function planningModeTier(planningMode: string): ColumnKeyTier {
  return planningMode === "tours"
    ? "tour"
    : planningMode === "stations"
      ? "station"
      : "bare";
}

/**
 * Which granularity tier a day×variation `key` belongs to, or `null` if it is
 * not a day×variation key. Mirrors the mode filter the summary/save code uses:
 * `basic` ↔ `bare`, `tours` ↔ `tour`, `stations` ↔ `station`.
 */
export function dayVariationTier(key: string): ColumnKeyTier | null {
  return parseDayVariationKey(key)?.tier ?? null;
}
