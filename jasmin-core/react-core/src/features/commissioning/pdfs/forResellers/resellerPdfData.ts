/**
 * Per-document data mapping for the reseller PDFs (invoice / delivery note).
 *
 * The invoice/DN ``pdfData`` object, the ``bankDetails`` block, the totals,
 * and the per-invoice payment-terms cascade are shared here by both the React
 * generator (``*PDFGenerator.tsx``) and the imperative upload helper
 * (``generate*PDF.tsx``) so the wire shape lives in exactly one place.
 *
 * ``buildInvoicePdfData`` takes the backend's authoritative ``tax_breakdown`` +
 * ``sum_netto`` / ``sum_brutto`` (quantized ROUND_HALF_UP per VAT rate — see
 * apps/commissioning/models/mixin.py) instead of re-deriving money on the
 * client, so the printed / ZUGFeRD totals match the persisted, legally-binding
 * document to the cent.
 */

import type {
  DeliveryNoteReseller,
  InvoiceReseller,
} from "@shared/api/generated/models";
import type { DeliveryNotePDFData } from "./DeliveryNotePDF";
import type { InvoicePDFData } from "./InvoicePDF";
import {
  taxBreakdownFromBackend,
  type LineItemBase,
  type Totals,
} from "./pdfBase";

export interface BankDetails {
  iban: string;
  bic: string;
  beneficiary: string;
}

type GetSetting = (key: string, defaultValue?: unknown) => unknown;

/** Tenant bank/beneficiary block for the invoice footer + QR + ZUGFeRD XML.
 * The Tenant model has NO plain ``bic`` column — the BIC lives in
 * ``sepa_creditor_bic`` (reading ``tenant.bic`` silently produced an empty
 * BIC in every EPC QR code and dropped the BICID from the ZUGFeRD XML). */
export function buildBankDetails(
  tenant: Record<string, unknown> | null | undefined,
): BankDetails {
  return {
    iban: (tenant?.iban as string) || "",
    bic: (tenant?.sepa_creditor_bic as string) || "",
    beneficiary: (tenant?.name as string) || "",
  };
}

export interface ResolvedPaymentTerms {
  days: number;
  earlyPaymentDiscountPercent: number | null;
  earlyPaymentDiscountDays: number | null;
}

/**
 * Per-invoice payment terms: the API returns the raw nullable per-reseller
 * columns; resolve per-reseller → tenant setting → hard-coded fallback.
 */
export function resolvePaymentTerms(
  invoiceRecord: InvoiceReseller | null | undefined,
  getSetting: GetSetting,
): ResolvedPaymentTerms {
  return {
    days:
      invoiceRecord?.reseller_payment_terms_in_days ??
      (getSetting("payment_terms_reseller_in_days") as number | undefined) ??
      14,
    earlyPaymentDiscountPercent:
      (invoiceRecord?.reseller_early_payment_discount_percent != null
        ? Number(invoiceRecord.reseller_early_payment_discount_percent)
        : null) ??
      (getSetting("early_payment_discount_percent") as
        | number
        | null
        | undefined) ??
      null,
    earlyPaymentDiscountDays:
      invoiceRecord?.reseller_early_payment_discount_days ??
      (getSetting("early_payment_discount_days") as
        | number
        | null
        | undefined) ??
      null,
  };
}

const toCents = (n: number) => Math.round(n * 100);

/**
 * Map a fetched invoice (the generated ``InvoiceReseller`` payload) to the
 * ``InvoicePDFData`` the PDF renders. Per-rate tax + totals come from the
 * backend's authoritative fields (see module docstring), NOT re-derived.
 */
export function buildInvoicePdfData(
  invoiceData: InvoiceReseller,
  bankDetails: BankDetails,
): InvoicePDFData {
  const lineItems =
    (invoiceData.line_items as unknown as LineItemBase[]) || [];
  const crateItems =
    (invoiceData.crate_items as unknown as LineItemBase[]) || [];

  const taxBreakdown = taxBreakdownFromBackend(invoiceData.tax_breakdown) ?? [];
  const netto =
    invoiceData.sum_netto != null
      ? Number(invoiceData.sum_netto)
      : taxBreakdown.reduce((sum, group) => sum + group.netto, 0);
  const brutto =
    invoiceData.sum_brutto != null
      ? Number(invoiceData.sum_brutto)
      : taxBreakdown.reduce((sum, group) => sum + group.brutto, 0);
  // Cents-exact difference (both inputs are 2dp) keeps binary-float noise out
  // of the QR amount + ZUGFeRD XML.
  const totals: Totals = {
    netto,
    tax: (toCents(brutto) - toCents(netto)) / 100,
    brutto,
  };

  return {
    invoice: {
      prefix: invoiceData.prefix ?? undefined,
      invoice_number: invoiceData.number ?? undefined,
      invoice_date: invoiceData.date ?? undefined,
      reseller_name: invoiceData.reseller_name,
      reseller_address: invoiceData.reseller_address,
      reseller_zip: invoiceData.reseller_zip,
      reseller_city: invoiceData.reseller_city,
      reseller_country: invoiceData.reseller_country,
      reseller_uid: invoiceData.reseller_uid,
      corresponding_delivery_notes:
        invoiceData.corresponding_delivery_notes || "-",
      is_finalized: invoiceData.is_finalized,
      finalized_at: invoiceData.finalized_at,
      company_name: bankDetails.beneficiary,
      document_hash: invoiceData.document_hash ?? "",
      document_type: invoiceData.document_type as string | undefined,
      cancels_invoice_number: invoiceData.cancels_invoice_number,
      correction_reason: invoiceData.correction_reason,
    },
    lineItems,
    crateItems,
    taxBreakdown,
    totals,
  };
}

/**
 * Map a fetched delivery note (generated ``DeliveryNoteReseller`` payload) to
 * its ``DeliveryNotePDFData``. Delivery notes carry no totals / tax.
 */
export function buildDeliveryNotePdfData(
  dnData: DeliveryNoteReseller,
): DeliveryNotePDFData {
  return {
    deliveryNote: {
      prefix: dnData.prefix ?? undefined,
      delivery_note_number: dnData.number ?? undefined,
      delivery_note_date: dnData.date ?? undefined,
      reseller_name: dnData.reseller_name,
      reseller_address: dnData.reseller_address,
      reseller_zip: dnData.reseller_zip,
      reseller_city: dnData.reseller_city,
      reseller_country: dnData.reseller_country,
      reseller_uid: undefined,
      is_finalized: dnData.is_finalized,
      finalized_at: dnData.finalized_at,
      document_hash:
        (dnData as { document_hash?: string | null }).document_hash ?? "",
    },
    lineItems: (dnData.line_items as unknown as LineItemBase[]) || [],
    crateItems: (dnData.crate_items as unknown as LineItemBase[]) || [],
  };
}
