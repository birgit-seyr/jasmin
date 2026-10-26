import dayjs, { type ConfigType, type Dayjs } from "dayjs";

/**
 * Canonical serializer for the ``YYYY-MM-DD`` wire format the backend expects
 * on API payloads and query params. This module is the single source of truth
 * for that literal — the ``useDateFormat().formatDateForAPI`` hook delegates here,
 * and plain (non-React) modules (services / hooks / utils) import this directly
 * because they can't call a hook.
 *
 * Accepts any dayjs ``ConfigType`` (``dayjs.Dayjs | string | number | Date |
 * null | undefined``). Returns ``null`` for falsy input, mirroring
 * ``formatDateForAPI`` — so callers building an optional query param keep the
 * same "omit when empty" behaviour.
 */
export function toApiDate(value: ConfigType): string | null {
  if (!value) return null;
  return formatApiDate(dayjs(value));
}

/**
 * Today's local calendar date in the same wire format. Not
 * ``new Date().toISOString().slice(0, 10)``: that is the date in UTC, which is
 * still the previous day for the first hour or two after local midnight.
 */
export function todayApiDate(): string {
  return formatApiDate(dayjs());
}

/** A date already in hand, in the same wire format. */
export function formatApiDate(day: Dayjs): string {
  return day.format("YYYY-MM-DD");
}
