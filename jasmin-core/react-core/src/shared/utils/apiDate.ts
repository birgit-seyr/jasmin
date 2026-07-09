import dayjs, { type ConfigType } from "dayjs";

/**
 * Canonical serializer for the ``YYYY-MM-DD`` wire format the backend expects
 * on API payloads and query params. This is the single source of truth for
 * that literal — the ``useDateFormat().formatDateForAPI`` hook delegates here,
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
  return dayjs(value).format("YYYY-MM-DD");
}
