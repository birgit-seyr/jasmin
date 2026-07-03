import dayjs from "dayjs";

/**
 * Is the selected ISO week more than one week in the past (i.e. read-only)?
 *
 * Mirrors exactly what ``WeekSelector`` used to emit via ``onPastChange``: a
 * week counts as "past" once it is >1 week behind the current week. Consumers
 * derive this directly from the year/week state they already own instead of
 * receiving it back through an effect-driven callback. A ``null`` week is not
 * past (matches the selector's previous no-emit behaviour).
 */
export function isWeekInPast(
  selectedYear: number | null | undefined,
  selectedWeek: number | null | undefined,
): boolean {
  if (!selectedYear || !selectedWeek) return false;
  const selectedDate = dayjs().year(selectedYear).isoWeek(selectedWeek);
  return dayjs().diff(selectedDate, "weeks") > 1;
}

/**
 * Is the selected year before the current year? Mirrors what ``YearSelector``
 * used to emit via ``onPastChange``.
 */
export function isYearInPast(
  selectedYear: number | null | undefined,
): boolean {
  if (!selectedYear) return false;
  return selectedYear < dayjs().year();
}

/**
 * The reference "active at" date for an ISO week — the week's Saturday
 * (isoWeekday 6) as ``YYYY-MM-DD``. Used to scope time-bound lookups (delivery
 * days, share types, …) to a given week. A null week falls back to the current
 * ISO week.
 */
export function activeAtDateForWeek(year: number, week: number | null): string {
  return dayjs()
    .year(year)
    .isoWeek(week ?? dayjs().isoWeek())
    .isoWeekday(6)
    .format("YYYY-MM-DD");
}
