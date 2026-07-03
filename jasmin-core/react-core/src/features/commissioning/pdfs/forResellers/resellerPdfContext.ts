/**
 * Shared tenant-PDF context assembly for the reseller documents
 * (delivery note / invoice / offer). Every generator repeated the same
 * three things: convert the tenant logo(s) to base64, build
 * ``tenantSettings`` / ``footerSettings`` / currency symbol, and read the
 * six ``entry_line_* / greeting_line_*`` (plus offer-only
 * ``order_instructions``) reseller-doc text settings. This module owns
 * that so each generator just picks its ``docType``.
 *
 * Lazy-loading: this module only re-uses the react-pdf-free helpers from
 * ``pdfBase`` (``buildTenantSettings`` / ``buildFooterSettings`` /
 * ``convertLogoToBase64``) plus the currency util — exactly what the
 * generators and the imperative ``generate*PDF`` twins already imported.
 * It adds no new ``@react-pdf/renderer`` coupling.
 */

import { useEffect, useState } from "react";
import { currencyCodeToSymbol } from "@shared/utils/currency";
import {
  buildFooterSettings,
  buildTenantSettings,
  convertLogoToBase64,
  type FooterSettings,
  type TenantPDFSettings,
} from "./pdfBase";

export type ResellerDocType = "delivery_note" | "invoice" | "offer";

/** ``{entry,greeting}_line_{1,2,3}_<doc>_reseller`` (+ offer-only
 *  ``order_instructions_offer_reseller``), all optional strings. */
export type ResellerLineSettings = Record<string, string | undefined>;

export interface ResellerPdfContext {
  tenantSettings: TenantPDFSettings;
  footerSettings: FooterSettings;
  currencySymbol: string;
  lineSettings: ResellerLineSettings;
}

type GetSetting = (key: string, defaultValue?: unknown) => unknown;

/**
 * Read the reseller-doc text settings for one document type. Accepts any
 * ``getSetting``-shaped reader, so it works with both the cached
 * ``TenantContext.getSetting`` (production generators) and the live
 * unsaved-edits reader on the settings page (``getSettingValue``).
 */
export function buildResellerLineSettings(
  getSetting: GetSetting,
  docType: ResellerDocType,
): ResellerLineSettings {
  const settings: ResellerLineSettings = {};
  for (const n of [1, 2, 3]) {
    const key = `entry_line_${n}_${docType}_reseller`;
    settings[key] = getSetting(key) as string | undefined;
  }
  // The offer carries an extra free-text "how to order" block between
  // the entry lines and the greeting.
  if (docType === "offer") {
    settings.order_instructions_offer_reseller = getSetting(
      "order_instructions_offer_reseller",
    ) as string | undefined;
  }
  for (const n of [1, 2, 3]) {
    const key = `greeting_line_${n}_${docType}_reseller`;
    settings[key] = getSetting(key) as string | undefined;
  }
  return settings;
}

function currencySymbolFrom(getSetting: GetSetting): string {
  return currencyCodeToSymbol((getSetting("currency") as string) || "EUR");
}

/**
 * Imperative (non-hook) twin for the ``generate*PDF`` upload helpers,
 * which run outside React and ``await`` the logo conversion.
 */
export async function buildResellerPdfContext({
  tenant,
  getSetting,
  logoUrl,
  bioLogoUrl,
  docType,
}: {
  tenant: Record<string, unknown>;
  getSetting: GetSetting;
  logoUrl: string | null | undefined;
  bioLogoUrl?: string | null;
  docType: ResellerDocType;
}): Promise<ResellerPdfContext> {
  const logoDataUrl = logoUrl ? await convertLogoToBase64(logoUrl) : null;
  const bioLogoDataUrl = bioLogoUrl
    ? await convertLogoToBase64(bioLogoUrl)
    : null;
  return {
    tenantSettings: buildTenantSettings(
      tenant,
      logoDataUrl,
      getSetting,
      bioLogoDataUrl,
    ),
    footerSettings: buildFooterSettings(getSetting),
    currencySymbol: currencySymbolFrom(getSetting),
    lineSettings: buildResellerLineSettings(getSetting, docType),
  };
}

/**
 * Hook twin for the React generator components. Converts the logo(s) to
 * base64 as they resolve, then derives the full PDF context. Pass the
 * values from ``useTenant()`` so the caller keeps a single
 * ``useTenant()`` call (some generators still need ``getSetting`` for
 * their own bits, e.g. invoice payment terms).
 */
export function useResellerPdfContext({
  tenant,
  getSetting,
  logoUrl,
  bioLogoUrl,
  docType,
}: {
  tenant: Record<string, unknown> | null;
  getSetting: GetSetting;
  logoUrl: string | null | undefined;
  bioLogoUrl?: string | null;
  docType: ResellerDocType;
}): ResellerPdfContext {
  const [logoDataUrl, setLogoDataUrl] = useState<string | null>(null);
  const [bioLogoDataUrl, setBioLogoDataUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!logoUrl) {
      setLogoDataUrl(null);
      return;
    }
    convertLogoToBase64(logoUrl).then(setLogoDataUrl);
  }, [logoUrl]);

  useEffect(() => {
    if (!bioLogoUrl) {
      setBioLogoDataUrl(null);
      return;
    }
    convertLogoToBase64(bioLogoUrl).then(setBioLogoDataUrl);
  }, [bioLogoUrl]);

  return {
    tenantSettings: buildTenantSettings(
      tenant,
      logoDataUrl,
      getSetting,
      bioLogoDataUrl,
    ),
    footerSettings: buildFooterSettings(getSetting),
    currencySymbol: currencySymbolFrom(getSetting),
    lineSettings: buildResellerLineSettings(getSetting, docType),
  };
}
