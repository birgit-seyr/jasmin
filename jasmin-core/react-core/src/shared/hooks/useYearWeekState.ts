import dayjs from "dayjs";
import { useState } from "react";
import { mondayOfIsoWeek } from "@shared/utils/weekRange";

export interface UseYearWeekStateOptions {
  /**
   * Offset (in ISO weeks) from the current week for the initial year and week
   * — e.g. ``1`` starts on next week (Offers / long-term planning). Rolls over
   * the year boundary: one week past week 52 (or 53) is week 1 of the next
   * year. Ignored for the week when ``initialWeek`` is provided, and for the
   * year when ``initialYear`` is.
   */
  weekOffset?: number;
  /** Explicit initial ``selectedWeek``. Overrides ``weekOffset``. */
  initialWeek?: number | null;
  /** Explicit initial ``selectedYear``. Defaults to the current year. */
  initialYear?: number;
  /**
   * The page offers "all weeks" (``WeekSelector``'s ``include_null_option``),
   * so ``selectedWeek`` can be ``null``. Without it the week is always set.
   */
  allWeeks?: boolean;
}

export interface UseYearWeekState<TWeek extends number | null = number> {
  selectedYear: number;
  setSelectedYear: (value: number) => void;
  selectedWeek: TWeek;
  setSelectedWeek: (value: TWeek) => void;
  /** The ISO week-year of the day the page mounted. */
  currentYear: number;
  /** The ISO week of the day the page mounted. */
  currentWeek: number;
}

/**
 * The year + week selector state (``selectedYear`` / ``selectedWeek`` plus their
 * setters) shared by the week-scoped report pages. ``selectedWeek`` is always a
 * week, unless the page passes ``allWeeks`` and so lets it be ``null`` ("all
 * weeks"); pass options for the pages whose defaults diverge.
 *
 * "Today" is read when the page mounts, never at module load: a tab left open
 * over midnight or New Year would otherwise open the page on a passed week.
 * ``currentYear`` / ``currentWeek`` keep that reading; they stay the same for
 * the page's lifetime, so they are safe in ``useMemo`` / ``useCallback`` deps.
 *
 * ``isoWeekYear()``, never the calendar ``year()``: the two disagree across
 * New Year, and the pair is sent to the API as one ISO coordinate. On
 * 2027-01-01 the calendar year is 2027 while the ISO week is 53 — a week ISO
 * 2027 does not have, which the backend refuses.
 */
export function useYearWeekState(
  options: UseYearWeekStateOptions & { allWeeks: true },
): UseYearWeekState<number | null>;
export function useYearWeekState(
  options?: UseYearWeekStateOptions & { allWeeks?: false; initialWeek?: number },
): UseYearWeekState<number>;
export function useYearWeekState(
  options: UseYearWeekStateOptions = {},
): UseYearWeekState<number> | UseYearWeekState<number | null> {
  const { weekOffset = 0, initialWeek, initialYear } = options;

  const [today] = useState(() => {
    const now = dayjs();
    return { year: now.isoWeekYear(), week: now.isoWeek() };
  });
  const [seed] = useState(() => {
    const monday = mondayOfIsoWeek(today.year, today.week).add(
      weekOffset,
      "week",
    );
    return { year: monday.isoWeekYear(), week: monday.isoWeek() };
  });
  const [selectedYear, setSelectedYear] = useState<number>(
    initialYear ?? seed.year,
  );
  const [selectedWeek, setSelectedWeek] = useState<number | null>(
    initialWeek !== undefined ? initialWeek : seed.week,
  );

  return {
    selectedYear,
    setSelectedYear,
    selectedWeek,
    setSelectedWeek,
    currentYear: today.year,
    currentWeek: today.week,
  };
}
