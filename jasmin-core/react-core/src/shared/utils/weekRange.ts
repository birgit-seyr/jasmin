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
 * Human label for the ISO weeks a whole-week ``[valid_from … valid_until]``
 * range covers. Bounds are contiguous whole weeks (valid_from = Monday,
 * valid_until = Sunday), so a first–last range names them all:
 *   - ``KW 27``                  — a single week
 *   - ``KW 27–30``               — several weeks in the same ISO year
 *   - ``KW 51/2026 – KW 2/2027`` — a span crossing the ISO-year boundary
 * Empty string when either bound is missing or unparseable. ``kwLabel`` is the
 * translated "KW" prefix, passed in so this stays i18n-free.
 */
export function isoWeekRangeLabel(
  validFrom: string | null | undefined,
  validUntil: string | null | undefined,
  kwLabel: string,
): string {
  if (!validFrom || !validUntil) return "";
  const start = dayjs(validFrom);
  const end = dayjs(validUntil);
  if (!start.isValid() || !end.isValid()) return "";

  const startWeek = start.isoWeek();
  const startYear = start.isoWeekYear();
  const endWeek = end.isoWeek();
  const endYear = end.isoWeekYear();

  if (startWeek === endWeek && startYear === endYear) {
    return `${kwLabel} ${startWeek}`;
  }
  if (startYear === endYear) {
    return `${kwLabel} ${startWeek}–${endWeek}`;
  }
  return `${kwLabel} ${startWeek}/${startYear} – ${kwLabel} ${endWeek}/${endYear}`;
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
