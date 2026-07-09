import dayjs from "dayjs";
import { useState } from "react";

/**
 * Current ISO year / week, computed once at module load — the SSOT for the
 * ``const currentYear = dayjs().year(); const currentWeek = dayjs().isoWeek();``
 * pair that ~18 pages were each declaring at module scope. Mirrors the existing
 * ``currentFiscalYearRange`` export beside ``useFiscalYearRange``.
 */
export const currentYear = dayjs().year();
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
 * setters) shared by the week-scoped report pages, collapsing the copy-pasted
 * ``dayjs().year()`` / ``dayjs().isoWeek()`` consts + two ``useState`` lines
 * into one hook. ``selectedWeek`` is nullable (``null`` = "all weeks"), matching
 * the dominant page shape; pass options for the pages whose defaults diverge.
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
