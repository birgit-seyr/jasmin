import dayjs from "dayjs";
import { useState } from "react";

/**
 * Current ISO week-year / week, computed once at module load — the SSOT every
 * week-scoped page seeds its selector from. Mirrors the
 * ``currentFiscalYearRange`` export beside ``useFiscalYearRange``.
 *
 * ``isoWeekYear()``, never the calendar ``year()``: the two disagree across
 * New Year, and the pair is sent to the API as one ISO coordinate. On
 * 2027-01-01 the calendar year is 2027 while the ISO week is 53 — a week ISO
 * 2027 does not have, which the backend refuses.
 */
export const currentYear = dayjs().isoWeekYear();
export const currentWeek = dayjs().isoWeek();

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
}

/**
 * The year + week selector state (``selectedYear`` / ``selectedWeek`` plus their
 * setters) shared by the week-scoped report pages. ``selectedWeek`` is nullable
 * (``null`` = "all weeks"), matching the dominant page shape; pass options for
 * the pages whose defaults diverge.
 *
 * For ``selectedWeek ?? currentWeek`` style fallbacks, import the module-level
 * {@link currentWeek} / {@link currentYear} consts — they stay module-scoped
 * (stable identity) so they don't trip ``react-hooks/exhaustive-deps`` when
 * referenced inside a ``useMemo`` / ``useCallback``.
 */
export function useYearWeekState(
  options: UseYearWeekStateOptions = {},
): UseYearWeekState {
  const { weekOffset = 0, initialWeek, initialYear } = options;

  const [selectedYear, setSelectedYear] = useState<number>(
    initialYear ?? currentYear,
  );
  const [selectedWeek, setSelectedWeek] = useState<number | null>(
    initialWeek !== undefined ? initialWeek : currentWeek + weekOffset,
  );

  return { selectedYear, setSelectedYear, selectedWeek, setSelectedWeek };
}
