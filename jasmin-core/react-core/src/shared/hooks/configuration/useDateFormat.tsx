import dayjs, { type ConfigType } from "dayjs";
import { useCallback } from "react";
import { useTenant } from "./useTenant";

export const useDateFormat = () => {
  const { getSetting, tenant } = useTenant();
  // Prefer the merged settings overlay (authenticated pages); fall back to
  // the tenant's top-level ``date_format`` scalar, which the anonymous
  // ``/tenants/current/`` payload carries (public privacy / impressum pages
  // have no settings overlay). Finally the German default.
  const dateFormat =
    (getSetting("date_format") as string | undefined) ??
    (tenant?.date_format as string | undefined) ??
    "DD.MM.YYYY";
  // Compact form for tight/mobile day labels (e.g. the day-selector strips):
  // the tenant date format with the year dropped, so it still tracks the
  // tenant's field order + separators. Keeps a trailing dot ("DD.MM." — the
  // German convention) but trims a dangling slash/dash/space left by removing
  // the year. Falls back to the full format if stripping leaves nothing.
  const mobileDateFormat =
    dateFormat
      .replace(/Y+/g, "")
      .replace(/^[\s./-]+/, "")
      .replace(/[\s/-]+$/, "") || dateFormat;

  const formatDate = useCallback(
    (value: ConfigType, customFormat: string | null = null) => {
      if (!value) return null;
      return dayjs(value).format(customFormat || dateFormat);
    },
    [dateFormat]
  );

  const formatDateWithFallback = useCallback(
    (value: ConfigType, fallback = "-", customFormat: string | null = null) => {
      if (!value) return fallback;
      return dayjs(value).format(customFormat || dateFormat);
    },
    [dateFormat]
  );

  const formatDateForAPI = useCallback((value: ConfigType) => {
    if (!value) return null;
    return dayjs(value).format("YYYY-MM-DD");
  }, []);

  const formatDateWithColor = useCallback(
    (value: ConfigType, customFormat: string | null = null) => {
      if (!value) return null;

      const date = dayjs(value);
      const today = dayjs().startOf("day");
      const formattedDate = date.format(customFormat || dateFormat);

      const isPast = date.isBefore(today, "day");
      const color = isPast ? "red" : "inherit";

      return <span style={{ color }}>{formattedDate}</span>;
    },
    [dateFormat]
  );

  return {
    dateFormat,
    mobileDateFormat,
    formatDate,
    formatDateWithFallback,
    formatDateForAPI,
    formatDateWithColor,
  };
};
