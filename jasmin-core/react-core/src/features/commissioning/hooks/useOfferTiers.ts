import { useMemo } from "react";
import { useTenant } from "@hooks/configuration/useTenant";

/**
 * The offer price tiers configured for this tenant
 * (``used_tiers_for_offers``) as an ordered list of quantity thresholds.
 * Falls back to single-tier ``[1]`` when unset — only ``price_1`` is ever
 * picked, no quantity-based escalation. Memoized so the fallback array keeps
 * a stable identity across renders (otherwise it would invalidate every memo
 * that lists the tiers as a dependency).
 *
 * Single source of truth shared by the offers + orders price-tier columns and
 * the offer-group tier-rabatt columns, so they always reflect the same tiers.
 */
export function useOfferTiers(): number[] {
  const { getSetting } = useTenant();
  const used = getSetting("used_tiers_for_offers") as number[] | undefined;
  return useMemo(() => (used && used.length > 0 ? used : [1]), [used]);
}
