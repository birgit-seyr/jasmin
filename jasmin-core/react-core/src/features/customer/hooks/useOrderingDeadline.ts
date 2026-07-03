import dayjs from "dayjs";
import { useMemo } from "react";

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

    // lastDay is 0-indexed (Mon=0), isoWeekday is 1-indexed (Mon=1)
    const deadlineDate = dayjs()
      .year(selectedYear)
      .isoWeek(selectedWeek)
      .isoWeekday(lastDay + 1);
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
