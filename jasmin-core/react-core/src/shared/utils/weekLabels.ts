import { getDayName } from "./weekdayNames";

type TranslateFn = (key: string) => string;

/**
 * Formats a week label like "KW12" using the translated KW prefix.
 */
export const formatWeekLabel = (
  week: number | string | null | undefined,
  t: TranslateFn,
): string => {
  if (week == null) return "";
  return `${t("commissioning.KW")}${week}`;
};

/**
 * Formats a day name from a day index, sanitized for filenames.
 * Returns empty string if day is null/undefined.
 */
export const formatDayLabel = (
  day: number | null | undefined,
  t: TranslateFn,
): string => {
  if (day == null) return "";
  return getDayName(day, t).replace(/[^a-zA-Z0-9]/g, "");
};
