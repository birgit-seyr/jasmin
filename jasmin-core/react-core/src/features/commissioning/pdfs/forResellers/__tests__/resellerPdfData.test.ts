/**
 * The reseller PDFs' data mapping: the tenant's bank block (BIC from
 * ``sepa_creditor_bic``), the payment terms cascade (reseller → tenant
 * setting → fallback) and the invoice totals, which come from the backend's
 * own sums so the printed document matches the stored one to the cent.
 */
import { describe, expect, it } from "vitest";

import type { DeliveryNoteReseller, InvoiceReseller } from "@shared/api/generated/models";

import {
  buildBankDetails,
  buildDeliveryNotePdfData,
  buildInvoicePdfData,
  resolvePaymentTerms,
} from "../resellerPdfData";

describe("buildBankDetails", () => {
  it("reads the BIC from the SEPA creditor BIC", () => {
    expect(
      buildBankDetails({
        iban: "DE89370400440532013000",
        bic: "WRONGBIC",
        sepa_creditor_bic: "COBADEFFXXX",
        name: "Green Farm",
      }),
    ).toEqual({ iban: "DE89370400440532013000", bic: "COBADEFFXXX", beneficiary: "Green Farm" });
  });

  it("gives empty strings without a tenant", () => {
    expect(buildBankDetails(null)).toEqual({ iban: "", bic: "", beneficiary: "" });
  });
});

describe("resolvePaymentTerms", () => {
  const settings: Record<string, unknown> = {
    payment_terms_reseller_in_days: 30,
    early_payment_discount_percent: 2,
    early_payment_discount_days: 10,
  };
  const getSetting = (key: string) => settings[key];

  it("prefers the reseller's own terms", () => {
    const invoice: InvoiceReseller = {
      reseller_payment_terms_in_days: 7,
      reseller_early_payment_discount_percent: "3.50",
      reseller_early_payment_discount_days: 5,
    };
    expect(resolvePaymentTerms(invoice, getSetting)).toEqual({
      days: 7,
      earlyPaymentDiscountPercent: 3.5,
      earlyPaymentDiscountDays: 5,
    });
  });

  it("keeps a reseller discount of zero over the tenant setting", () => {
    const invoice: InvoiceReseller = { reseller_early_payment_discount_percent: "0" };
    expect(resolvePaymentTerms(invoice, getSetting).earlyPaymentDiscountPercent).toBe(0);
  });

  it("falls back to the tenant settings", () => {
    expect(resolvePaymentTerms({}, getSetting)).toEqual({
      days: 30,
      earlyPaymentDiscountPercent: 2,
      earlyPaymentDiscountDays: 10,
    });
  });

  it("falls back to 14 days and no discount without any setting", () => {
    expect(resolvePaymentTerms(null, () => undefined)).toEqual({
      days: 14,
      earlyPaymentDiscountPercent: null,
      earlyPaymentDiscountDays: null,
    });
  });
});

describe("buildInvoicePdfData", () => {
  const bank = { iban: "DE89370400440532013000", bic: "COBADEFFXXX", beneficiary: "Green Farm" };
  const breakdown = [
    { rate: "7.00", netto: "10.10", tax: "0.71", brutto: "10.81" },
    { rate: "19.00", netto: "0.20", tax: "0.04", brutto: "0.24" },
  ];

  it("takes the totals from the backend's sums, cents-exact", () => {
    const data = buildInvoicePdfData(
      { sum_netto: "10.30", sum_brutto: "11.05", tax_breakdown: breakdown, prefix: "RE", number: 4 },
      bank,
    );
    expect(data.totals).toEqual({ netto: 10.3, tax: 0.75, brutto: 11.05 });
    expect(data.taxBreakdown).toEqual([
      { rate: 7, netto: 10.1, tax: 0.71, brutto: 10.81 },
      { rate: 19, netto: 0.2, tax: 0.04, brutto: 0.24 },
    ]);
    expect(data.invoice).toMatchObject({
      prefix: "RE",
      invoice_number: 4,
      company_name: "Green Farm",
      corresponding_delivery_notes: "-",
      document_hash: "",
    });
  });

  it("sums the tax breakdown when the backend sends no totals", () => {
    const data = buildInvoicePdfData({ tax_breakdown: breakdown }, bank);
    expect(data.totals.netto).toBeCloseTo(10.3, 10);
    expect(data.totals.brutto).toBeCloseTo(11.05, 10);
    expect(data.totals.tax).toBe(0.75);
  });

  it("prints zero totals for an invoice without lines", () => {
    const data = buildInvoicePdfData({}, bank);
    expect(data.taxBreakdown).toEqual([]);
    expect(data.totals).toEqual({ netto: 0, tax: 0, brutto: 0 });
  });
});

describe("buildDeliveryNotePdfData", () => {
  it("maps the delivery note without a VAT ID and with its hash", () => {
    const note: DeliveryNoteReseller = {
      prefix: "LS",
      number: 9,
      date: "2026-10-05",
      reseller_name: "Corner Shop",
      is_finalized: true,
    };
    const data = buildDeliveryNotePdfData(note);
    expect(data.deliveryNote).toMatchObject({
      prefix: "LS",
      delivery_note_number: 9,
      delivery_note_date: "2026-10-05",
      reseller_name: "Corner Shop",
      reseller_uid: undefined,
      is_finalized: true,
      document_hash: "",
    });
  });
});
