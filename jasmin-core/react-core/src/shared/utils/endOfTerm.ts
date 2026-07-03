import dayjs, { type Dayjs } from "dayjs";

/**
 * Map ``ShareType.delivery_cycle`` (canonical backend values) to the
 * number of CALENDAR WEEKS between deliveries.
 *
 * Used to convert the tenant's trial length (``count of deliveries``)
 * into a Sunday-aligned ``valid_until``. Month-based cycles are kept
 * as their weeks-equivalent (4 / 13 / 26 / 52) so the result lands on
 * a Sunday deterministically — calendar-month arithmetic would force
 * a Sunday-snap and surface DST / month-length edge cases. The office
 * can override ``valid_until`` for non-weekly variations where this
 * approximation drifts (e.g. a 3-MONTHLY trial of ~13.0 vs 13.04
 * weeks).
 *
 * Unknown / null cycle falls back to ``1`` (WEEKLY) — matches the
 * backend default and keeps the auto-fill safe for legacy rows
 * without an explicit delivery_cycle.
 */
const WEEKS_PER_DELIVERY_BY_CYCLE: Record<string, number> = {
  WEEKLY: 1,
  ODD_WEEKS: 2,
  EVEN_WEEKS: 2,
  MONTHLY: 4,
  QUARTERLY: 13,
  HALF_YEARLY: 26,
  YEARLY: 52,
};

export function weeksPerDelivery(
  cycle: string | null | undefined,
): number {
  if (!cycle) return 1;
  return WEEKS_PER_DELIVERY_BY_CYCLE[cycle] ?? 1;
}

/**
 * Tenant flags that drive the end-of-term computation. Mirrors the
 * relevant subset of ``TenantSettings`` so the function can be
 * unit-tested without instantiating the full context.
 */
export interface EndOfTermSettings {
  /** Tenant runs a season-based cadence — every subscription ends
   *  together at the season transition. */
  subscriptionsEndAtEndOfSeason: boolean;
  /** Tenant uses a plain one-year term — ``valid_until = valid_from
   *  + 52 weeks - 1 day`` (Sunday, deterministic since valid_from
   *  is a Monday). */
  subscriptionsEndAfterOneYear: boolean;
  /** ISO calendar week (1-53) on which a season opens. Required when
   *  ``subscriptionsEndAtEndOfSeason`` is on. */
  seasonStartWeek: number | null | undefined;
  /** The row is a trial subscription. When ``true``, neither the
   *  season nor the one-year branch applies — the trial duration
   *  below wins. */
  isTrial?: boolean;
  /** ``TenantSettings.allowed_trial_subscription_duration`` — count
   *  of deliveries the trial covers. Combined with
   *  ``trialWeeksPerDelivery`` (derived from the picked variation's
   *  ``ShareType.delivery_cycle`` via ``weeksPerDelivery``) to span
   *  the right number of calendar weeks. */
  trialDurationInDeliveries?: number | null | undefined;
  /** Calendar weeks between deliveries for the trial's variation —
   *  1 (WEEKLY), 2 (ODD/EVEN_WEEKS), 4 (MONTHLY), 13 (QUARTERLY),
   *  26 (HALF_YEARLY), 52 (YEARLY). Defaults to ``1`` when missing
   *  so a brand-new row with no variation picked yet still gets a
   *  reasonable auto-fill. */
  trialWeeksPerDelivery?: number | null | undefined;
}

/**
 * Compute the ``valid_until`` Sunday for a new subscription, applying
 * the tenant's configured end-of-term rule.
 *
 * Branches (highest priority first):
 *   * ``isTrial`` AND ``trialDurationInDeliveries >= 1`` →
 *     ``validFrom + (N * trialWeeksPerDelivery) weeks - 1 day``
 *     (Sunday). Cycle-aware: a 4-delivery trial spans 4 weeks for a
 *     WEEKLY variation, 8 weeks for an ODD_WEEKS / EVEN_WEEKS
 *     variation, ~16 weeks (4 × 4) for a MONTHLY one, and so on
 *     (see ``WEEKS_PER_DELIVERY_BY_CYCLE``). This branch wins over
 *     the season / one-year branches so a trial inside a
 *     season-based tenant still gets its short ad-hoc term.
 *   * ``subscriptionsEndAtEndOfSeason`` AND a valid
 *     ``seasonStartWeek`` (1–53):
 *       - ``validFromWeek >= seasonStartWeek`` → joining THIS year's
 *         new season → ends just before NEXT year's season starts
 *         (Sunday of week ``seasonStartWeek - 1`` in year+1).
 *       - ``validFromWeek <  seasonStartWeek`` → late join in the
 *         prior season's window → Sunday OF ``seasonStartWeek`` in
 *         the same year.
 *   * ``subscriptionsEndAfterOneYear`` → ``validFrom + 52 weeks - 1
 *     day`` (Sunday, assuming validFrom is a Monday).
 *   * None applicable → ``null`` (caller decides whether to leave
 *     the field blank or fall back to a manual value).
 */
export function computeValidUntil(
  validFrom: Dayjs,
  settings: EndOfTermSettings,
): Dayjs | null {
  if (!validFrom.isValid()) return null;

  const {
    subscriptionsEndAtEndOfSeason,
    subscriptionsEndAfterOneYear,
    seasonStartWeek,
    isTrial,
    trialDurationInDeliveries,
    trialWeeksPerDelivery,
  } = settings;

  if (isTrial) {
    const n = Math.floor(Number(trialDurationInDeliveries));
    if (Number.isFinite(n) && n >= 1) {
      // valid_from is always a Monday (validFromColumn enforces).
      // Cycle-aware: span = N deliveries × weeks-per-delivery
      // (defaults to 1 when unspecified — WEEKLY). Both factors
      // are integers (PositiveIntegerField on the setting +
      // hand-curated WEEKS_PER_DELIVERY_BY_CYCLE map), so the
      // ``Math.floor`` calls are defensive belt-and-braces against
      // bad input rather than an active rounding step. Result:
      // +integer weeks preserves the weekday (Monday stays
      // Monday); -1 day lands on Sunday. Same Sunday-deterministic
      // shape as the one-year branch.
      const wpdRaw = Number(trialWeeksPerDelivery);
      const wpd =
        Number.isFinite(wpdRaw) && wpdRaw >= 1 ? Math.floor(wpdRaw) : 1;
      return validFrom.add(n * wpd, "week").subtract(1, "day");
    }
    // Trial with no configured duration → no auto-fill. Office
    // types the end date manually instead of getting a wrong
    // long-term default.
    return null;
  }

  if (
    subscriptionsEndAtEndOfSeason &&
    seasonStartWeek != null &&
    Number.isFinite(Number(seasonStartWeek)) &&
    Number(seasonStartWeek) >= 1 &&
    Number(seasonStartWeek) <= 53
  ) {
    const weekNo = Number(seasonStartWeek);
    const validFromYear = validFrom.year();
    const validFromWeek = validFrom.isoWeek();

    if (validFromWeek >= weekNo) {
      // Sunday of (weekNo - 1) in (validFromYear + 1) = Monday of
      // weekNo in (validFromYear + 1) minus 1 day.
      return dayjs()
        .year(validFromYear + 1)
        .isoWeek(weekNo)
        .isoWeekday(1)
        .subtract(1, "day");
    }
    // Sunday OF seasonWeek in the same year.
    return dayjs()
      .year(validFromYear)
      .isoWeek(weekNo)
      .isoWeekday(7);
  }

  if (subscriptionsEndAfterOneYear) {
    // valid_from is always a Monday (validFromColumn enforces).
    // +52 weeks preserves the weekday → Monday next year; -1 day
    // lands on Sunday. Deterministic, no Sunday-snap needed.
    return validFrom.add(52, "week").subtract(1, "day");
  }

  return null;
}

/**
 * Loose date-string → Dayjs parser used at office-input boundaries.
 * The office can type values in the tenant's display format or in
 * canonical ISO; this tries display first, then ISO. Returns
 * ``null`` (not an invalid Dayjs) on failure so callers can ``if
 * (!parsed) return``.
 */
export function parseDateLoose(
  value: unknown,
  displayFormat: string,
): Dayjs | null {
  if (!value) return null;
  if (dayjs.isDayjs(value)) return value.isValid() ? value : null;
  if (typeof value !== "string") return null;
  let parsed = dayjs(value, displayFormat, true);
  if (!parsed.isValid()) {
    parsed = dayjs(value, "YYYY-MM-DD", true);
  }
  return parsed.isValid() ? parsed : null;
}
