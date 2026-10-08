import dayjs from "dayjs";
import { useState } from "react";

export interface UseYearWeekStateOptions {
  /**
   * Offset (in ISO weeks) from the current week for the initial ``selectedWeek``
   * — e.g. ``1`` starts on next week (Offers / long-term planning). Ignored when
   * ``initialWeek`` is provided.
   */
  weekOffset?: number;
  /** Explicit initial ``selectedWeek`` (``null`` = "all weeks"). Overrides ``weekOffset``. */
  initialWeek?: number | null;
  /** Explicit initial ``selectedYear``. Defaults to the current year. */
  initialYear?: number;
}

export interface UseYearWeekState {
  selectedYear: number;
  setSelectedYear: (value: number) => void;
  selectedWeek: number | null;
  setSelectedWeek: (value: number | null) => void;
  /** The ISO week-year of the day the page mounted. */
  currentYear: number;
  /** The ISO week of the day the page mounted. */
  currentWeek: number;
}

/**
 * The year + week selector state (``selectedYear`` / ``selectedWeek`` plus their
 * setters) shared by the week-scoped report pages. ``selectedWeek`` is nullable
 * (``null`` = "all weeks"), matching the dominant page shape; pass options for
 * the pages whose defaults diverge.
 *
 * "Today" is read when the page mounts, never at module load: a tab left open
 * over midnight or New Year would otherwise open the page on a passed week.
 * ``currentYear`` / ``currentWeek`` keep that reading for the page's
 * ``selectedWeek ?? currentWeek`` fallbacks; they stay the same for the page's
 * lifetime, so they are safe in ``useMemo`` / ``useCallback`` deps.
 *
 * ``isoWeekYear()``, never the calendar ``year()``: the two disagree across
 * New Year, and the pair is sent to the API as one ISO coordinate. On
 * 2027-01-01 the calendar year is 2027 while the ISO week is 53 — a week ISO
 * 2027 does not have, which the backend refuses.
 */
export function useYearWeekState(
  options: UseYearWeekStateOptions = {},
): UseYearWeekState {
  const { weekOffset = 0, initialWeek, initialYear } = options;

  const [today] = useState(() => {
    const now = dayjs();
    return { year: now.isoWeekYear(), week: now.isoWeek() };
  });
  const [selectedYear, setSelectedYear] = useState<number>(
    initialYear ?? today.year,
  );
  const [selectedWeek, setSelectedWeek] = useState<number | null>(
    initialWeek !== undefined ? initialWeek : today.week + weekOffset,
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
