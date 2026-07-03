import dayjs, { type Dayjs } from "dayjs";

/**
 * The next Sunday on or after ``referenceDate`` (default: today) — the earliest
 * a cancellation can take effect, because the server's ``TimeBoundMixin``
 * requires ``valid_until`` to fall on a Sunday. The single source for both the
 * cancel-date picker floor AND the Cancel-button visibility, so the two stay in
 * lockstep.
 */
export function getNextSunday(referenceDate?: Dayjs): Dayjs {
  const today = (referenceDate ?? dayjs()).startOf("day");
  const daysUntilSunday = (7 - today.day()) % 7; // dayjs: 0=Sun
  return today.add(daysUntilSunday, "day");
}
