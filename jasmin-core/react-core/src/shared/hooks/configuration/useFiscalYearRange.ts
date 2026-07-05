import dayjs, { type Dayjs } from "dayjs";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTenant } from "./useTenant";

/**
 * The current fiscal year as a ``[start, end]`` range: the 1st of the tenant's
 * ``fiscal_year_start_month`` (in the current fiscal year) through one year
 * later, minus a day (so April-start → Apr 1 … Mar 31). If today is before
 * this year's fiscal-start month, the current fiscal year began LAST year.
 * ``fiscalStartMonth`` is 1–12; anything falsy/out-of-range falls back to
 * January.
 */
export function currentFiscalYearRange(
  fiscalStartMonth: number | null | undefined,
): [Dayjs, Dayjs] {
  const month = Math.min(Math.max(fiscalStartMonth || 1, 1), 12);
  let start = dayjs()
    .month(month - 1)
    .startOf("month");
  if (start.isAfter(dayjs(), "day")) start = start.subtract(1, "year");
  const end = start.add(1, "year").subtract(1, "day");
  return [start, end];
}

/**
 * Range-picker state seeded to the tenant's current fiscal year. The tenant
 * payload loads asynchronously (``tenant`` is null on first render), so the
 * seed re-syncs to the real fiscal year once it arrives — UNLESS the user has
 * already changed the range, in which case their choice is kept. Returns the
 * range (nullable, since the picker can be cleared) and a setter that marks the
 * range as user-owned.
 */
export function useFiscalYearRangeState(): [
  [Dayjs, Dayjs] | null,
  (range: [Dayjs, Dayjs] | null) => void,
] {
  const { tenant } = useTenant();
  const fiscalStartMonth = tenant?.fiscal_year_start_month;
  const fiscalDefault = useMemo(
    () => currentFiscalYearRange(fiscalStartMonth),
    [fiscalStartMonth],
  );

  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(fiscalDefault);
  const userOwned = useRef(false);

  // Re-seed when the fiscal month becomes known (tenant finished loading) as
  // long as the user hasn't taken ownership of the range yet.
  useEffect(() => {
    if (!userOwned.current) setRange(fiscalDefault);
  }, [fiscalDefault]);

  const setRangeOwned = useCallback((next: [Dayjs, Dayjs] | null) => {
    userOwned.current = true;
    setRange(next);
  }, []);

  return [range, setRangeOwned];
}
