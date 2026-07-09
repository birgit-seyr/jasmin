import { StyleSheet } from "@react-pdf/renderer";
import "../registerRoboto";
import { DocumentTypeEnum } from "@shared/api/generated/models";
import { formatNumber } from "@shared/utils/numberFormat";
import { itemLineNetto, roundHalfUp } from "@shared/utils/lineNetto";

/**
 * A storno or correction is a credit note (ZUGFeRD TypeCode 381, positive
 * amounts, and a reference back to the original invoice). The single predicate
 * for the reseller-document credit-note rule so the visible PDF, the stored
 * filename, and the embedded XML never disagree.
 */
export function isCreditNote(documentType?: string | null): boolean {
  return (
    documentType === DocumentTypeEnum.storno ||
    documentType === DocumentTypeEnum.correction
  );
}

// ─── Shared types ───────────────────────────────────────────────────────────

export interface TenantPDFSettings {
  logo?: string | null;
  /** EU 2018/848 organic-certification mark. Data URL (loaded via
   * ``convertLogoToBase64`` in the generators). Rendered next to the
   * organic-control-number disclosure on invoice / delivery-note PDFs.
   * ``null``/``undefined`` → no mark image; the text-only disclosure
   * still appears when the tenant has an ``organic_control_number``. */
  bio_logo?: string | null;
  name?: string;
  address?: string;
  zip_code?: string;
  city?: string;
  country?: string;
  email?: string;
  email_for_orders?: string;
  phone_number?: string;
  uid?: string;
  payment_terms_reseller_in_days?: number;
  /**
   * Tenant-level Skonto default (per-reseller override on
   * ``Reseller.early_payment_discount_percent``). Both fields must be
   * set for the Skonto line to render. Either NULL → no Skonto offered
   * by default.
   */
  early_payment_discount_percent?: number | null;
  early_payment_discount_days?: number | null;
  /** BCP-47 number locale, e.g. "de-DE". Drives decimal/grouping in PDFs. */
  number_locale?: string;
  /** EU 2018/848 Bio-Kontrollstellen-Nr. (e.g. "DE-ÖKO-XXX"). When
   * non-empty, ``ShareArticle.organic_status`` flows into the line
   * suffix ("*"/"**") and a footer disclosure references this number.
   * Empty → the whole organic feature is suppressed on PDFs (matches
   * the office-side gate via ``useOrganicGate``). */
  organic_control_number?: string | null;
}

export interface FooterSettings {
  left_column_footer_documents_reseller?: string;
  middle_column_footer_documents_reseller?: string;
  right_column_footer_documents_reseller?: string;
}

export interface ResellerInfo {
  reseller_name?: string | null;
  reseller_address?: string | null;
  reseller_zip?: string | null;
  reseller_city?: string | null;
  reseller_country?: string | null;
  reseller_uid?: string | null;
}

export type OrganicStatus = "organic" | "in_conversion" | "conventional";

export interface LineItemBase {
  share_article_name?: string;
  crate_type_name?: string;
  sort?: string;
  amount: number;
  price_per_unit: number;
  unit?: string;
  size?: string;
  tax_rate?: number;
  rabatt?: number;
  /** Net line total (supplied by the backend; see models/mixin.py). */
  line_netto?: number | string;
  /** EU 2018/848 disclosure on the ShareArticle. Lines with
   * ``"organic"`` get a single asterisk suffix on the PDF; lines with
   * ``"in_conversion"`` get double. ``"conventional"`` is unmarked.
   * Whichever footer lines the PDF renders depends on which marks
   * actually appear in the document. */
  organic_status?: OrganicStatus;
}

/** Suffix appended to the article name on customer-facing PDFs.
 * Returns ``""`` for conventional / unknown so caller can blindly
 * concatenate. */
export function organicMarker(status: OrganicStatus | undefined): string {
  if (status === "organic") return " *";
  if (status === "in_conversion") return " **";
  return "";
}

/** "Has any organic / in-conversion line?" probe used by PDF footers
 * to decide which control-number disclosure rows to print. */
export function organicMarksPresent(items: LineItemBase[]): {
  hasOrganic: boolean;
  hasInConversion: boolean;
} {
  let hasOrganic = false;
  let hasInConversion = false;
  for (const item of items) {
    if (item.organic_status === "organic") hasOrganic = true;
    else if (item.organic_status === "in_conversion") hasInConversion = true;
    if (hasOrganic && hasInConversion) break;
  }
  return { hasOrganic, hasInConversion };
}

export interface TaxBreakdownItem {
  rate: number;
  netto: number;
  tax: number;
  brutto: number;
}

export interface Totals {
  netto: number;
  tax: number;
  brutto: number;
}

// ─── Shared styles ──────────────────────────────────────────────────────────

export const baseStyles = StyleSheet.create({
  page: {
    paddingLeft: 40,
    paddingRight: 40,
    paddingTop: 60,
    paddingBottom: 120,
    fontSize: 10,
    fontFamily: "Roboto",
  },
  header: {
    position: "absolute",
    top: 200,
    left: 40,
  },
  logoContainer: {
    position: "absolute",
    top: 40,
    right: 40,
    width: 120,
    height: 60,
  },
  logo: {
    width: "100%",
    height: "100%",
    objectFit: "contain",
  },
  resellerInfoContainer: {
    position: "absolute",
    top: 100,
    left: 40,
  },
  title: {
    fontSize: 18,
    fontWeight: "bold",
    marginBottom: 5,
  },
  section: {
    marginTop: 80,
    marginBottom: 10,
    width: "100%",
    alignItems: "flex-end",
  },
  label: {
    textAlign: "right",
    marginBottom: 3,
  },
  table: {
    marginTop: 0,
    marginBottom: 10,
  },
  tableHeader: {
    flexDirection: "row",
    borderBottomWidth: 2,
    borderBottomColor: "#000",
    paddingBottom: 5,
    marginBottom: 5,
    marginTop: 0,
    fontWeight: "bold",
    backgroundColor: "#fff",
  },
  tableRow: {
    flexDirection: "row",
    paddingVertical: 3,
    borderBottomWidth: 1,
    borderBottomColor: "#ddd",
  },
  col1: { width: "30%" },
  col2: { width: "8%", textAlign: "right", paddingRight: 5 },
  col3: { width: "8%", textAlign: "left", paddingLeft: 5 },
  col4: { width: "18%", textAlign: "right", paddingRight: 5 },
  col5: { width: "8%", textAlign: "center", paddingRight: 5 },
  col6: { width: "8%", textAlign: "center", paddingRight: 5 },
  col7: { width: "20%", textAlign: "right", paddingRight: 5 },
  greetingSection: {
    width: "100%",
    marginTop: 10,
    marginBottom: 10,
  },
  entrySection: {
    width: "100%",
    marginBottom: 8,
  },
  hashBar: {
    position: "absolute",
    bottom: 30,
    left: 40,
    right: 40,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: 5,
    fontSize: 7,
    color: "#666",
  },
  footer: {
    position: "absolute",
    bottom: 50,
    left: 40,
    right: 40,
    flexDirection: "row",
    justifyContent: "space-between",
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: "#ddd",
    fontSize: 9,
  },
  footerColumn: {
    width: "30%",
    fontSize: 9,
    lineHeight: 1.3,
  },
  footerLeft: {
    textAlign: "left",
  },
  footerMiddle: {
    textAlign: "center",
  },
  footerRight: {
    textAlign: "right",
  },
  text_grey: {
    fontSize: 8,
    color: "#666",
    marginBottom: 5,
  },
  // Muted grey for secondary/placeholder labels (sort line, LOGO / QR preview
  // placeholders). @react-pdf resolves no CSS custom properties, so these must
  // be a literal — the hex ``--color-text-tertiary`` maps to.
  text_muted: {
    color: "#767676",
  },
  divider: {
    borderTopWidth: 1,
    borderTopColor: "#ddd",
    marginTop: -4,
    marginBottom: 6,
  },
  row: {},
});

// ─── Shared helpers ─────────────────────────────────────────────────────────

/**
 * Format an amount for PDF display. Locale-aware via the caller-supplied
 * locale (PDFs are non-React-context, so the locale must be threaded in
 * explicitly — callers usually read it from `useNumberFormat().locale`
 * one level up and pass it through).
 */
export function formatAmount(
  amount: number,
  unit?: string,
  locale: string = "de-DE",
): string {
  const numValue = Number(amount);
  if (isNaN(numValue) || numValue === 0) return "";
  const decimals = !unit || unit === "KG" ? 2 : 1;
  return formatNumber(numValue, decimals, locale);
}

/**
 * Canonical tax-breakdown algorithm — mirrors backend `tax_breakdown` in
 * apps/commissioning/models/mixin.py:
 *   1. Sum net per tax_rate group.
 *   2. Quantize net to 2 decimals (ROUND_HALF_UP).
 *   3. tax  = round(net * rate / 100, 2)  (ROUND_HALF_UP)
 *   4. brutto = round(net + tax, 2)       (ROUND_HALF_UP)
 *
 * Note: the reseller invoice/delivery-note PDFs no longer call this — they
 * render the backend's authoritative ``tax_breakdown`` directly (see
 * resellerPdfData.ts). It remains the client-side fallback for InvoiceModal and
 * the order-total estimate in useOrdersData.
 *
 * Pass any number of item iterables (article items, crate items, …); they are
 * grouped together by rate so combined brutto matches the backend exactly.
 */
export function computeTaxBreakdown(
  ...itemGroups: LineItemBase[][]
): TaxBreakdownItem[] {
  const buckets: Record<string, { rate: number; netto: number }> = {};
  for (const items of itemGroups) {
    for (const item of items) {
      const rate = Number(item.tax_rate || 0);
      const key = rate.toString();
      if (!buckets[key]) buckets[key] = { rate, netto: 0 };
      buckets[key].netto += itemLineNetto(item);
    }
  }
  return Object.values(buckets)
    .sort((a, b) => a.rate - b.rate)
    .map(({ rate, netto }) => {
      const nettoR = roundHalfUp(netto);
      const taxR = roundHalfUp((nettoR * rate) / 100);
      const bruttoR = roundHalfUp(nettoR + taxR);
      return { rate, netto: nettoR, tax: taxR, brutto: bruttoR };
    });
}

/** Sum a breakdown into the document totals (netto, tax, brutto). */
export function totalsFromBreakdown(breakdown: TaxBreakdownItem[]): Totals {
  const totals = breakdown.reduce(
    (acc, g) => ({
      netto: acc.netto + g.netto,
      tax: acc.tax + g.tax,
      brutto: acc.brutto + g.brutto,
    }),
    { netto: 0, tax: 0, brutto: 0 },
  );
  return {
    netto: roundHalfUp(totals.netto),
    tax: roundHalfUp(totals.tax),
    brutto: roundHalfUp(totals.brutto),
  };
}

/**
 * Map the backend's authoritative ``tax_breakdown`` payload (per-rate decimal
 * STRINGS, see TaxBreakdownFieldMixin in serializers_mixin.py) into numeric
 * ``TaxBreakdownItem``s for rendering. Prefer this over re-deriving on the
 * client: the backend values are the persisted, legally-binding figures.
 * Returns ``null`` when the payload is missing/empty/malformed so callers can
 * fall back to ``computeTaxBreakdown``.
 */
export function taxBreakdownFromBackend(
  raw: unknown,
): TaxBreakdownItem[] | null {
  if (!Array.isArray(raw) || raw.length === 0) return null;
  const parsed: TaxBreakdownItem[] = [];
  for (const group of raw) {
    if (!group || typeof group !== "object") return null;
    const row = group as Record<string, unknown>;
    const rate = Number(row.rate);
    const netto = Number(row.netto);
    const tax = Number(row.tax);
    const brutto = Number(row.brutto);
    if (![rate, netto, tax, brutto].every(Number.isFinite)) return null;
    parsed.push({ rate, netto, tax, brutto });
  }
  return parsed;
}


/**
 * Convert a remote image URL to a base64 data URL for embedding in PDFs.
 */
export async function convertLogoToBase64(
  logoUrl: string,
): Promise<string | null> {
  try {
    const response = await fetch(logoUrl);
    const blob = await response.blob();
    return await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => resolve(reader.result as string);
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  } catch (err) {
    console.error("Failed to convert logo:", err);
    return null;
  }
}

/**
 * Build tenant settings object for PDF components from useTenant() data.
 */
export function buildTenantSettings(
  tenant: Record<string, unknown> | null,
  logoDataUrl: string | null,
  getSetting: (key: string, defaultValue?: unknown) => unknown,
  bioLogoDataUrl: string | null = null,
): TenantPDFSettings {
  return {
    logo: logoDataUrl,
    bio_logo: bioLogoDataUrl,
    name: (tenant?.name as string) ?? undefined,
    address: (tenant?.address as string) ?? undefined,
    zip_code: (tenant?.zip_code as string) ?? undefined,
    city: (tenant?.city as string) ?? undefined,
    country: (tenant?.country as string) ?? undefined,
    email: (tenant?.email as string) ?? undefined,
    email_for_orders: (tenant?.email_for_orders as string) ?? undefined,
    phone_number: (tenant?.phone_number as string) ?? undefined,
    uid: (tenant?.uid as string) ?? undefined,
    payment_terms_reseller_in_days: getSetting(
      "payment_terms_reseller_in_days",
    ) as number | undefined,
    early_payment_discount_percent: getSetting(
      "early_payment_discount_percent",
    ) as number | null | undefined,
    early_payment_discount_days: getSetting(
      "early_payment_discount_days",
    ) as number | null | undefined,
    number_locale:
      (getSetting("number_locale", "de-DE") as string) || "de-DE",
    organic_control_number:
      (tenant?.organic_control_number as string | null | undefined) ?? null,
  };
}

/**
 * Build footer settings object from getSetting.
 */
export function buildFooterSettings(
  getSetting: (key: string, defaultValue?: unknown) => unknown,
): FooterSettings {
  return {
    left_column_footer_documents_reseller: getSetting(
      "left_column_footer_documents_reseller",
    ) as string | undefined,
    middle_column_footer_documents_reseller: getSetting(
      "middle_column_footer_documents_reseller",
    ) as string | undefined,
    right_column_footer_documents_reseller: getSetting(
      "right_column_footer_documents_reseller",
    ) as string | undefined,
  };
}
