/**
 * Single source of truth for "may this share_type_variation be used for a TRIAL
 * subscription?". A variation opts OUT explicitly with
 * ``allowed_for_trial_subscription === false``; missing / true → allowed.
 *
 * Shared by the abos table (``is_trial`` column disable), the
 * NewSubscriptionModal Probe/Anteil picker filter, and the registration
 * variation step, so all three agree on which variations a trial can pick.
 */

/** Minimal shape — anything carrying the flag (a variation option, a raw
 *  ShareTypeVariation, …). */
export interface TrialAllowable {
  allowed_for_trial_subscription?: boolean | null;
}

/** True unless the variation explicitly forbids trials. */
export function variationAllowsTrial(
  variation: TrialAllowable | null | undefined,
): boolean {
  return variation?.allowed_for_trial_subscription !== false;
}

/** When ``isTrial`` is on, keep only trial-allowed variations; otherwise pass
 *  them all through. Returns the same array reference when not filtering. */
export function filterVariationsForTrial<T extends TrialAllowable>(
  variations: T[],
  isTrial: boolean,
): T[] {
  return isTrial ? variations.filter(variationAllowsTrial) : variations;
}
