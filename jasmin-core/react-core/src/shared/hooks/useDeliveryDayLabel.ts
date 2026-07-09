import { useCallback } from "react";
import { dateForWeekDayNumber } from "@shared/utils/weekRange";
import { useDateFormat } from "./configuration/useDateFormat";
import { useIsMobile } from "./configuration/useIsMobile";

/**
 * Returns a formatter for a delivery day's localized label within an ISO week.
 * The label is ``dddd, <tenant date format>`` on desktop and ``dd, <mobile
 * format>`` on mobile, honoring the tenant's ``useDateFormat`` settings. The
 * ``dayNumber`` is the backend ``day_number`` (0 = Monday); an out-of-range /
 * null day yields an empty string.
 */
export function useDeliveryDayLabel() {
  const isMobile = useIsMobile();
  const { dateFormat, mobileDateFormat } = useDateFormat();

  return useCallback(
    (
      year: number,
      week: number,
      dayNumber: number | null | undefined,
    ): string => {
      if (dayNumber == null) return "";
      const date = dateForWeekDayNumber(year, week, Number(dayNumber));
      return isMobile
        ? date.format(`dd, ${mobileDateFormat}`)
        : date.format(`dddd, ${dateFormat}`);
    },
    [isMobile, dateFormat, mobileDateFormat],
  );
}
