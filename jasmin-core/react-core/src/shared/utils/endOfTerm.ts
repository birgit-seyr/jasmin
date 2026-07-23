import dayjs, { type Dayjs } from "dayjs";

/**
 * Monday of ISO ``week`` in ISO ``year``, computed DETERMINISTICALLY (no
 * ``dayjs()`` wall-clock seed — the isoWeek SETTER is a relative move, so a
 * ``dayjs().year(y).isoWeek(w)`` construction leaks today's month/day into the
 * anchor and breaks at year boundaries). Jan 4 is always in ISO week 1, so its
 * Monday is week 1's Monday; adding ``week - 1`` weeks lands on the target week
 * — and a week past the year's last (53 in a 52-week year) rolls forward
 * exactly like the backend ``isoweek`` library. Mirrors
 * ``subscription_term._sunday_before_iso_week`` so create (frontend) and
 * renewal (backend) agree on every date, at every wall-clock.
 */
function mondayOfIsoWeek(isoYear: number, week: number): Dayjs {
  return dayjs(`${isoYear}-01-04`)
    .isoWeekday(1)
    .add(week - 1, "week");
}

/**
 * Map ``ShareType.delivery_cycle`` (canonical backend values) to the
 * number of CALENDAR WEEKS between deliveries.
 *
 * Used to convert the tenant's trial length (``count of deliveries``)
 * into a Sunday-aligned ``valid_until``. Every cycle is a plain week
 * stride, so the span is exact: N deliveries × weeks-per-delivery from
 * a Monday ``valid_from`` lands on a Monday, and ``- 1 day`` makes it a
 * deterministic Sunday.
 *
 * Unknown / null cycle falls back to ``1`` (WEEKLY) — matches the
 * backend default and keeps the auto-fill safe for legacy rows without
 * an explicit delivery_cycle. Keep in sync with the backend
 * ``services/delivery_cycle.py``.
 */
const WEEKS_PER_DELIVERY_BY_CYCLE: Record<string, number> = {
  WEEKLY: 1,
  ODD_WEEKS: 2,
  EVEN_WEEKS: 2,
  ALL_THREE_WEEKS: 3,
  ALL_FOUR_WEEKS: 4,
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
   *  1 (WEEKLY), 2 (ODD/EVEN_WEEKS), 3 (ALL_THREE_WEEKS),
   *  4 (ALL_FOUR_WEEKS). Defaults to ``1`` when missing so a brand-new
   *  row with no variation picked yet still gets a reasonable auto-fill. */
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
 *     variation, 16 weeks (4 × 4) for an ALL_FOUR_WEEKS one (see
 *     ``WEEKS_PER_DELIVERY_BY_CYCLE``). This branch wins over
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
 *   * ``subscriptionsEndAfterOneYear`` → the Sunday before Monday of
 *     ``validFrom``'s ISO week in the NEXT ISO year (anchored to the
 *     week, not a fixed +52 weeks, so the yearly restart week stays
 *     stable across 52- and 53-week ISO years).
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
    // ``isoWeekYear()`` (not calendar ``year()``): a valid_from in ISO week 1
    // that falls in late December has calendar year Y-1 but ISO week-year Y.
    const validFromWeekYear = validFrom.isoWeekYear();
    const validFromWeek = validFrom.isoWeek();

    if (validFromWeek >= weekNo) {
      // Ends the day before the season opens NEXT ISO year.
      return mondayOfIsoWeek(validFromWeekYear + 1, weekNo).subtract(1, "day");
    }
    // Late join: ends on the Sunday OF the season week THIS ISO year.
    return mondayOfIsoWeek(validFromWeekYear, weekNo).add(6, "day");
  }

  if (subscriptionsEndAfterOneYear) {
    // Anchor the end to the SAME ISO week next year (NOT a fixed +52 weeks).
    // valid_from is a Monday of ISO week W, so the term ends the day before
    // Monday of week W next ISO year. This keeps the yearly restart on week W
    // across 52- and 53-week ISO years — a fixed +364 days would slip the
    // restart back one week whenever a 53-week year falls inside the term.
    // Deterministic (via ``mondayOfIsoWeek``) and ``isoWeekYear()``-based so it
    // stays correct at year boundaries and matches the backend
    // ``subscription_term.compute_term_valid_until``.
    return mondayOfIsoWeek(
      validFrom.isoWeekYear() + 1,
      validFrom.isoWeek(),
    ).subtract(1, "day");
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
