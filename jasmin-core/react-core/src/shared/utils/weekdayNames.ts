// Single source of truth for weekday-name i18n keys, indexed by the backend
// day_number: 0 = Monday … 6 = Sunday (matches SharesDeliveryDay.day_number /
// DayNumberOptions). NOTE Monday is 0 — a falsy `!dayNumber` guard would
// silently drop Mondays; always compare against null. Framework-agnostic (bare
// i18n keys, no i18next import) and shared with ``stationDayLabel``.
export const WEEKDAY_KEYS = [
  "common.weekday_monday",
  "common.weekday_tuesday",
  "common.weekday_wednesday",
  "common.weekday_thursday",
  "common.weekday_friday",
  "common.weekday_saturday",
  "common.weekday_sunday",
] as const;

// Short delivery-day i18n keys, same 0 = Monday … 6 = Sunday indexing as
// ``WEEKDAY_KEYS``. These render the abbreviated label the delivery UIs show;
// ``WEEKDAY_KEYS`` renders the full weekday name.
export const DELIVERY_DAY_SHORT_KEYS = [
  "delivery.mo",
  "delivery.di",
  "delivery.mi",
  "delivery.do",
  "delivery.fr",
  "delivery.sa",
  "delivery.su",
] as const;

/**
 * Uppercase localized weekday name for a 0=Monday..6=Sunday day index. Used by
 * the PDF / filename helpers that want the ALL-CAPS day token. Falls back to the
 * 1-based day number when the index is null or out of range.
 */
export const getDayName = (
  dayIndex: number | null,
  t: (key: string) => string,
): string => {
  const key = dayIndex == null ? undefined : WEEKDAY_KEYS[dayIndex];
  const name = key ? t(key).toUpperCase() : undefined;
  return name || `${(dayIndex ?? 0) + 1}`;
};
