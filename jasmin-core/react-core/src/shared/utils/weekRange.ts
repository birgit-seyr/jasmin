import dayjs, { type Dayjs } from "dayjs";
import { toApiDate } from "./apiDate";

/**
 * Monday of ISO ``week`` in ISO ``year``, computed DETERMINISTICALLY (no
 * ``dayjs()`` wall-clock seed — the isoWeek SETTER is a relative move, so a
 * ``dayjs().year(y).isoWeek(w)`` construction leaks today's month/day into the
 * anchor and breaks at year boundaries). Jan 4 is always in ISO week 1, so its
 * Monday is week 1's Monday; adding ``week - 1`` weeks lands on the target week
 * — and a week past the year's last (53 in a 52-week year) rolls forward
 * exactly like the backend ``isoweek`` library. Mirrors
 * ``subscription_term._sunday_before_iso_week`` so the frontend and the backend
 * agree on every date, at every wall-clock.
 */
export function mondayOfIsoWeek(isoYear: number, week: number): Dayjs {
  return dayjs(`${isoYear}-01-04`)
    .isoWeekday(1)
    .add(week - 1, "week");
}

/**
 * The ISO week after `week` of ISO year `year`. A year with 53 ISO weeks
 * reaches week 53 before the next year's week 1.
 */
export function nextIsoWeek(
  year: number,
  week: number,
): { year: number; week: number } {
  const monday = mondayOfIsoWeek(year, week).add(1, "week");
  return { year: monday.isoWeekYear(), week: monday.isoWeek() };
}

/**
 * Is the selected ISO week more than one week in the past (i.e. read-only)?
 *
 * A week counts as "past" once it is >1 week behind the current week.
 * Consumers derive this directly from the year/week state they already own.
 * A ``null`` week is not past.
 */
export function isWeekInPast(
  selectedYear: number | null | undefined,
  selectedWeek: number | null | undefined,
): boolean {
  if (!selectedYear || !selectedWeek) return false;
  return dayjs().diff(mondayOfIsoWeek(selectedYear, selectedWeek), "weeks") > 1;
}

/**
 * Has the selected ISO week begun — is its Monday today or earlier?
 *
 * Stricter than ``isWeekInPast``: the share days endpoint refuses a change to
 * such a week unless it is forced. A ``null`` week has not begun.
 */
export function hasWeekBegun(
  selectedYear: number | null | undefined,
  selectedWeek: number | null | undefined,
): boolean {
  if (!selectedYear || !selectedWeek) return false;
  return !mondayOfIsoWeek(selectedYear, selectedWeek).isAfter(dayjs(), "day");
}

/**
 * Is the selected year before the current year?
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
  return toApiDate(mondayOfIsoWeek(year, week ?? dayjs().isoWeek()).add(5, "day"))!;
}

/**
 * The calendar date of a delivery day within a given ISO week. ``dayNumber`` is
 * the backend ``day_number`` (0 = Monday … 6 = Sunday), so it counts the days
 * after the week's Monday. Returns a Dayjs so callers can either format it
 * (labels) or compare ``.valueOf()`` (sort comparators).
 */
export function dateForWeekDayNumber(
  year: number,
  week: number,
  dayNumber: number,
): Dayjs {
  return mondayOfIsoWeek(year, week).add(Number(dayNumber), "day");
}
