import type { TFunction } from "i18next";
import { WEEKDAY_KEYS } from "./dayNamesUtil";

/** Localized full weekday name for a 0=Monday..6=Sunday day_number. */
export function weekdayLabel(
  t: TFunction,
  dayNumber: number | string | null | undefined,
): string {
  if (dayNumber == null || dayNumber === "") return "";
  const index = Number(dayNumber);
  if (!Number.isInteger(index) || index < 0 || index > 6) return "";
  return t(WEEKDAY_KEYS[index]);
}

/** "<station short_name> — <weekday>" label for a member-facing station-day row. */
export function formatStationDayLabel(
  t: TFunction,
  row: {
    delivery_station_short_name?: string | null;
    delivery_day_number?: number | string | null;
  },
): string {
  const weekday = weekdayLabel(t, row.delivery_day_number);
  const station = row.delivery_station_short_name || "";
  if (station && weekday) return `${station} — ${weekday}`;
  return station || weekday || "—";
}
