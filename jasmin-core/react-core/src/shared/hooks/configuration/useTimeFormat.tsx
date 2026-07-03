import dayjs, { type ConfigType } from "dayjs";
import { useCallback } from "react";
import { useTenant } from "./useTenant";

/**
 * Tenant-scoped time formatter — analog of {@link useDateFormat}.
 *
 * Reads ``TenantSettings.time_format`` (e.g. ``"HH:mm"``,
 * ``"hh:mm A"``) so every UI surface that prints a time-of-day stays
 * in the same shape per tenant.
 *
 * Three helpers:
 *
 * * ``formatTime(value)`` — pure formatter; returns ``null`` for empty
 *   input (matches ``useDateFormat.formatDate``).
 * * ``formatTimeWithFallback(value, fallback="-")`` — for read-only UI
 *   where ``null`` would render as the literal word "null".
 * * ``formatDateTime(value, dateOnlyFormat?)`` — convenience for
 *   timestamps shown as ``<date> <time>``. Uses
 *   ``TenantSettings.date_format`` for the date half by default; pass
 *   ``dateOnlyFormat`` to override (e.g. weekday prefix).
 *
 * Format tokens are dayjs tokens (so ``H``, ``HH``, ``h``, ``hh``,
 * ``m``, ``mm``, ``A``, ``a``). The default ``"HH:mm"`` matches the
 * backend default on ``TenantSettings``.
 */
export const useTimeFormat = () => {
  const { getSetting } = useTenant();
  const timeFormat =
    (getSetting("time_format", "HH:mm") as string | undefined) ?? "HH:mm";
  const dateFormat =
    (getSetting("date_format", "DD.MM.YYYY") as string | undefined) ??
    "DD.MM.YYYY";

  const formatTime = useCallback(
    (value: ConfigType, customFormat: string | null = null) => {
      if (!value) return null;
      return dayjs(value).format(customFormat || timeFormat);
    },
    [timeFormat],
  );

  const formatTimeWithFallback = useCallback(
    (value: ConfigType, fallback = "-", customFormat: string | null = null) => {
      if (!value) return fallback;
      return dayjs(value).format(customFormat || timeFormat);
    },
    [timeFormat],
  );

  const formatDateTime = useCallback(
    (
      value: ConfigType,
      dateOnlyFormat: string | null = null,
      timeOnlyFormat: string | null = null,
    ) => {
      if (!value) return null;
      return dayjs(value).format(
        `${dateOnlyFormat || dateFormat} ${timeOnlyFormat || timeFormat}`,
      );
    },
    [dateFormat, timeFormat],
  );

  const formatDateTimeWithFallback = useCallback(
    (
      value: ConfigType,
      fallback = "-",
      dateOnlyFormat: string | null = null,
      timeOnlyFormat: string | null = null,
    ) => {
      if (!value) return fallback;
      return dayjs(value).format(
        `${dateOnlyFormat || dateFormat} ${timeOnlyFormat || timeFormat}`,
      );
    },
    [dateFormat, timeFormat],
  );

  return {
    timeFormat,
    // The tenant date format is resolved here too (for ``formatDateTime``);
    // expose it so callers that need a weekday-prefixed date (e.g.
    // ``dddd, ${dateFormat}``) don't hardcode the date half.
    dateFormat,
    formatTime,
    formatTimeWithFallback,
    formatDateTime,
    formatDateTimeWithFallback,
  };
};
