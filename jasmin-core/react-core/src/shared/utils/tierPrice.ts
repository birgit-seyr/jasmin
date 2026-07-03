/**
 * Reseller-style tiered price-per-unit picker — single source of truth.
 *
 * Why this exists: the same tier-dispatch was being computed in three
 * places (Orders live + save, InvoiceModal live, CustomerOrderPage
 * mutations) with two subtly different conventions (typed amount in
 * KG/PCS/BUNCH vs already in PU). When the divisor or threshold
 * comparison drifted between sites, prices disagreed depending on
 * which path ran. This module is the canonical implementation.
 *
 * Tier convention (per tenant setting ``used_tiers_for_offers``):
 *   - ``finalTiers`` is the array of tier thresholds (in PU) as
 *     configured by the tenant. May have 1, 2, or 3 entries.
 *   - If ``finalTiers[2]`` exists, ``puCount >= finalTiers[2]``, and
 *     ``price_3 > 0`` → use ``price_3``.
 *   - Else if ``finalTiers[1]`` exists, ``puCount >= finalTiers[1]``,
 *     and ``price_2 > 0`` → use ``price_2``.
 *   - Else ``price_1`` (the single / base tier).
 *
 * **No hardcoded default thresholds.** If the tenant hasn't configured
 * ``used_tiers_for_offers``, callers should pass ``[1]`` (or just
 * omit / pass ``[]``) — meaning single-tier mode: always ``price_1``,
 * regardless of quantity. Previously this defaulted to ``[1, 3, 5]``,
 * which silently bumped tenants who never set the field into 3-tier
 * pricing. See ``docs/todos/text.txt`` for the discussion.
 *
 * The ``price_X > 0`` fallback is intentional: tenants on multi-tier
 * who leave a higher tier's price empty (0) silently fall back to the
 * next-lower tier rather than charging 0.
 */

export interface TierPrices {
  price_1?: number | string | null;
  price_2?: number | string | null;
  price_3?: number | string | null;
}

/**
 * Pure tier picker. Caller computes ``puCount`` from whatever convention
 * the page uses (raw amount if it's already PU, ``amount / amount_per_pu``
 * otherwise — or just use ``pickTierPriceFromAmount`` below).
 */
export function pickTierPrice(
  puCount: number,
  prices: TierPrices,
  finalTiers: number[] = [],
): number {
  const p1 = Number(prices.price_1) || 0;
  const p2 = Number(prices.price_2) || 0;
  const p3 = Number(prices.price_3) || 0;
  // ``undefined`` t2 / t3 means the tenant didn't configure that tier
  // — never escalate, even for huge quantities.
  const t2 = finalTiers[1];
  const t3 = finalTiers[2];

  if (t3 !== undefined && puCount >= t3 && p3 > 0) return p3;
  if (t2 !== undefined && puCount >= t2 && p2 > 0) return p2;
  return p1;
}

/**
 * Convenience for pages where the user types the amount in the row's
 * unit (KG / PCS / BUNCH) and ``amount_per_pu`` tells us the
 * conversion factor to PU. Computes ``puCount = amount / amount_per_pu``
 * then delegates to ``pickTierPrice``.
 *
 * Use ``pickTierPrice`` directly on pages where the typed amount is
 * already PU (e.g. CustomerOrderPage).
 */
export function pickTierPriceFromAmount(
  amount: number | string | null | undefined,
  amountPerPu: number | string | null | undefined,
  prices: TierPrices,
  finalTiers: number[] = [],
): number {
  const numAmount = Number(amount) || 0;
  const perPu = Number(amountPerPu) || 1;
  const puCount = perPu > 0 ? numAmount / perPu : numAmount;
  return pickTierPrice(puCount, prices, finalTiers);
}
