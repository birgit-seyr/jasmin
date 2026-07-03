import { getDayName } from "./dayNamesUtil";

type TranslateFn = (key: string) => string;

/**
 * Generates a standardized filename from parts.
 * Sanitizes each part by replacing whitespace with underscores.
 * Usage: generatePdfFilename([t("commissioning.cleaning_list"), year, formatWeekLabel(week, t), formatDayLabel(day, t)])
 */
export const generatePdfFilename = (
  parts: (string | number | null | undefined | false)[],
): string => {
  return parts
    .filter((p): p is string | number => p != null && p !== false && p !== "")
    .map((p) => String(p).replace(/\s+/g, "_"))
    .join("_");
};

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
