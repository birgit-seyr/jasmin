import { useMemo } from "react";
import { useTenant } from "./useTenant";

/**
 * Platform-wide fallback VAT rates, mirroring the backend ``TenantSettings``
 * model defaults (``DEFAULT_TAX_RATE`` / ``DEFAULT_CRATE_TAX_RATE`` in
 * ``apps/commissioning/constants.py``): articles/shares default to 7 %,
 * crates (reusable-box deposit) to 19 %. Used only when a tenant hasn't
 * configured its own default tax rates.
 */
const DEFAULT_TAX_RATE_ARTICLES = 7;
const DEFAULT_TAX_RATE_CRATES = 19;
const DEFAULT_TAX_RATE_SHARES = 7;

export interface DefaultTaxRates {
  /** Default tax rate (%) for share articles / share prices. */
  articles: number;
  /** Default tax rate (%) for reusable-box (crate) prices. */
  crates: number;
  /** Default tax rate (%) for share (subscription) prices. */
  shares: number;
}

/**
 * Single source for the default tax rates applied to new pricing rows.
 * Resolves the tenant's configured ``default_tax_rate_articles`` /
 * ``default_tax_rate_crates`` settings, falling back to the platform
 * defaults when a setting is unset — replacing the inline ``?? 7`` /
 * ``?? 19`` fallbacks that used to be duplicated across the price modals,
 * the invoice/delivery-note modals and the orders data hook.
 */
export function useDefaultTaxRates(): DefaultTaxRates {
  const { getSetting } = useTenant();
  return useMemo(
    () => ({
      articles:
        getSetting("default_tax_rate_articles") ?? DEFAULT_TAX_RATE_ARTICLES,
      crates: getSetting("default_tax_rate_crates") ?? DEFAULT_TAX_RATE_CRATES,
      shares: getSetting("default_tax_rate_shares") ?? DEFAULT_TAX_RATE_SHARES,
    }),
    [getSetting],
  );
}
