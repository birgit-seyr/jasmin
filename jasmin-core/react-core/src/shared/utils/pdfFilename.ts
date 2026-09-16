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
