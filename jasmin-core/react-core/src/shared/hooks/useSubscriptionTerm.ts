import dayjs, { type Dayjs } from "dayjs";
import { useCallback, useMemo } from "react";
import {
  computeValidUntil as computeTermValidUntil,
  weeksPerDelivery,
} from "@shared/utils/endOfTerm";
import { useTenant } from "./configuration/useTenant";

/**
 * Single source of truth for a subscription's end-of-term rules, shared by
 * the abos table ({@link file://./@features/abos/pages/Abos.tsx}) and the
 * NewSubscriptionModal. Reads the tenant flags once and wraps the pure
 * {@link computeTermValidUntil} math so callers never re-derive the settings
 * → ``valid_until`` mapping (or drift out of sync) themselves.
 */
export const useSubscriptionTerm = () => {
  const { getSetting, tenant } = useTenant();

  // The anonymous registration page has no settings overlay (getSetting →
  // null), so fall back to the top-level scalars the anonymous
  // ``/tenants/current/`` payload carries (CurrentTenantSerializer).
  const read = (key: string): unknown => {
    const v = getSetting(key);
    if (v !== null && v !== undefined) return v;
    return (tenant as Record<string, unknown> | null | undefined)?.[key];
  };

  const allowsTrial =
    (read("allows_trial_subscriptions") as boolean | null | undefined) ?? true;
  const endOfSeason =
    (read("subscriptions_end_at_end_of_season") as
      | boolean
      | null
      | undefined) ?? false;
  // Mirrors the model default (``TenantSettings.subscriptions_end_after_one_year``
  // is ``default=True``): when the flag is absent from the overlay we assume the
  // one-year term applies, matching what the backend will compute on save.
  const endAfterOneYear =
    (read("subscriptions_end_after_one_year") as boolean | null | undefined) ??
    true;
  const seasonStartWeek =
    (read("season_start_week") as number | null | undefined) ?? null;
  // Trial length in deliveries; ``null`` when unset → no trial auto-fill.
  const trialDurationInDeliveries =
    (read("allowed_trial_subscription_duration") as
      | number
      | null
      | undefined) ?? null;
  // Lead time before a subscription may begin (weeks from "now").
  const minWeeksToStartDelivery =
    (read("min_weeks_from_creation_to_start_delivery") as
      | number
      | null
      | undefined) ?? 0;

  // Earliest a subscription may start: the first Monday on or after
  // ``now + minWeeksToStartDelivery`` weeks. ``valid_from`` must be a Monday
  // (TimeBoundMixin), so we snap forward to one. Computed at mount (the
  // ``dayjs()`` "now" is fine to freeze for the lifetime of a form).
  const earliestValidFrom = useMemo(() => {
    const base = dayjs()
      .startOf("day")
      .add(Math.max(0, minWeeksToStartDelivery), "week");
    const daysToMonday = (1 - base.day() + 7) % 7; // dayjs: 0=Sun, 1=Mon
    return base.add(daysToMonday, "day");
  }, [minWeeksToStartDelivery]);

  /** Sunday ``valid_until`` for the term, or ``null`` when no tenant rule
   *  applies (caller leaves the field for manual entry). ``cycle`` is the
   *  picked variation's ``ShareType.delivery_cycle`` (drives trial span). */
  const computeValidUntil = useCallback(
    (
      validFrom: Dayjs,
      { isTrial, cycle }: { isTrial: boolean; cycle?: string | null },
    ): Dayjs | null =>
      computeTermValidUntil(validFrom, {
        subscriptionsEndAtEndOfSeason: endOfSeason,
        subscriptionsEndAfterOneYear: endAfterOneYear,
        seasonStartWeek,
        isTrial,
        trialDurationInDeliveries,
        trialWeeksPerDelivery: weeksPerDelivery(cycle ?? null),
      }),
    [endOfSeason, endAfterOneYear, seasonStartWeek, trialDurationInDeliveries],
  );

  /** Whether ``valid_until`` is fully determined by tenant config for the
   *  given ``isTrial`` (so the field should be read-only). Mirrors the
   *  branch conditions in {@link computeTermValidUntil}, independent of the
   *  actual ``valid_from`` date. */
  const isValidUntilAuto = useCallback(
    (isTrial: boolean): boolean => {
      if (isTrial) {
        return (
          trialDurationInDeliveries != null && trialDurationInDeliveries >= 1
        );
      }
      const seasonApplies =
        endOfSeason &&
        seasonStartWeek != null &&
        seasonStartWeek >= 1 &&
        seasonStartWeek <= 53;
      return Boolean(seasonApplies || endAfterOneYear);
    },
    [endOfSeason, endAfterOneYear, seasonStartWeek, trialDurationInDeliveries],
  );

  /** ``disabledDate`` for ``valid_from``: Mondays only, no earlier than
   *  {@link earliestValidFrom}. Typed ``(current: unknown)`` so it satisfies
   *  both AntD's ``DatePicker`` (modal) and ``EditableColumnConfig`` (abos
   *  table) — one rule, no drift. */
  const disabledValidFromDate = useCallback(
    (current: unknown): boolean => {
      const date = current as Dayjs;
      return (
        !!date && (date.day() !== 1 || date.isBefore(earliestValidFrom, "day"))
      );
    },
    [earliestValidFrom],
  );

  return {
    allowsTrial,
    endOfSeason,
    endAfterOneYear,
    seasonStartWeek,
    trialDurationInDeliveries,
    minWeeksToStartDelivery,
    earliestValidFrom,
    computeValidUntil,
    isValidUntilAuto,
    disabledValidFromDate,
  };
};
