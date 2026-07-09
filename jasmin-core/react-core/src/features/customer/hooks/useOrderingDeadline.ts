import dayjs from "dayjs";
import { useMemo } from "react";
import { dateForWeekDayNumber } from "@shared/utils";

type OddDefaults = {
  default_last_possible_ordering_day: number | null;
  default_last_possible_ordering_time: string | null;
} | null;

export function useOrderingDeadline(
  oddDefaults: OddDefaults,
  selectedYear: number,
  selectedWeek: number,
) {
  return useMemo(() => {
    const lastDay = oddDefaults?.default_last_possible_ordering_day;
    const lastTime = oddDefaults?.default_last_possible_ordering_time;
    if (lastDay == null) {
      return { orderingDeadline: null, isOrderingClosed: false };
    }

    const deadlineDate = dateForWeekDayNumber(selectedYear, selectedWeek, lastDay);
    let deadline: dayjs.Dayjs;
    if (lastTime) {
      const [h, m] = lastTime.split(":").map(Number);
      deadline = deadlineDate.hour(h).minute(m).second(0);
    } else {
      deadline = deadlineDate.endOf("day");
    }
    return {
      orderingDeadline: deadline,
      isOrderingClosed: dayjs().isAfter(deadline),
    };
  }, [oddDefaults, selectedYear, selectedWeek]);
}
