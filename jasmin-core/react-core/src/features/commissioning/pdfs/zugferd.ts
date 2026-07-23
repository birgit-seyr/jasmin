import type { TFunction } from "i18next";
import {
  organicStatusLabel,
  type OrganicStatus,
} from "@hooks/configuration/useOrganicGate";
import {
  isCreditNote,
  organicMarksPresent,
  type LineItemBase,
  type TaxBreakdownItem,
  type TenantPDFSettings,
  type Totals,
} from "./forResellers/pdfBase";

// ─── Types ──────────────────────────────────────────────────────────────────

interface BankDetails {
  iban: string;
  bic?: string;
  beneficiary: string;
}

interface InvoiceData {
  prefix?: string;
  invoice_number?: string | number;
  invoice_date?: string;
  reseller_name?: string | null;
  reseller_address?: string | null;
  reseller_zip?: string | null;
  reseller_city?: string | null;
  reseller_country?: string | null;
  reseller_uid?: string | null;
  document_hash?: string;
  company_name?: string;
  /** "invoice" | "storno" | "correction" — drives the credit-note
   * TypeCode (381) and the positive-amount convention. */
  document_type?: string;
  /** Number of the original invoice a storno/correction reverses (BG-3
   * preceding-invoice reference). */
  cancels_invoice_number?: string | null;
}

interface ZUGFeRDInput {
  invoice: InvoiceData;
  lineItems: LineItemBase[];
  crateItems: LineItemBase[];
  taxBreakdown: TaxBreakdownItem[];
  totals: Totals;
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function escapeXml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

/** Map free-text country names (German + English) and 3-letter codes to
 * the ISO 3166-1 alpha-2 code that BR-CL-14 requires. Returns the input
 * upper-cased if it already looks like a 2-letter code; falls back to
 * ``"AT"`` for blank input. */
function toIso3166Alpha2(country: string | null | undefined): string {
  if (!country) return "AT";
  const v = country.trim().toUpperCase();
  if (/^[A-Z]{2}$/.test(v)) return v;
  const map: Record<string, string> = {
    ÖSTERREICH: "AT", OESTERREICH: "AT", AUSTRIA: "AT", AUT: "AT",
    DEUTSCHLAND: "DE", GERMANY: "DE", DEU: "DE",
    SCHWEIZ: "CH", SWITZERLAND: "CH", SUISSE: "CH", CHE: "CH",
    ITALIEN: "IT", ITALY: "IT", ITA: "IT",
    FRANKREICH: "FR", FRANCE: "FR", FRA: "FR",
    SLOWENIEN: "SI", SLOVENIA: "SI", SVN: "SI",
    UNGARN: "HU", HUNGARY: "HU", HUN: "HU",
    TSCHECHIEN: "CZ", "CZECH REPUBLIC": "CZ", CZE: "CZ",
  };
  return map[v] ?? "AT";
}

/** Ensure a VAT identifier starts with an ISO 3166-1 alpha-2 country
 * prefix (BR-CO-09). If the tenant stored just the local part
 * (e.g. ``U12345678``), we prepend the seller's country code. */
function ensureVatPrefix(vatId: string, sellerCountry: string): string {
  const trimmed = vatId.trim().replace(/\s+/g, "").toUpperCase();
  if (/^[A-Z]{2}/.test(trimmed)) return trimmed;
  return `${sellerCountry}${trimmed}`;
}

/** Map our internal unit codes to UN/ECE Recommendation 20 codes that
 * BR-CL-23 requires. Falls back to ``C62`` ("one") which is the safe
 * "unitless thing" code per Rec 20 when we don't know better. */
function toUnEceUnitCode(unit: string | null | undefined): string {
  if (!unit) return "C62";
  const map: Record<string, string> = {
    KG: "KGM",   // kilogram
    G: "GRM",    // gram
    L: "LTR",    // litre
    ML: "MLT",   // millilitre
    PCS: "H87",  // piece
    PC: "H87",
    EACH: "H87",
    BUNCH: "C62",  // no Rec 20 code for "bunch" — fall back to unit
    BUND: "C62",
    BOX: "BX",   // box (Rec 21)
    PACK: "PK",  // pack (Rec 21)
  };
  const v = unit.trim().toUpperCase();
  return map[v] ?? "C62";
}

/** Strip whitespace from an IBAN (BR-DE-19 wants ``DE89370400440532013000``
 * not ``DE89 3704 0044 0532 0130 00``). */
function normalizeIban(iban: string): string {
  return iban.replace(/\s+/g, "").toUpperCase();
}

function formatDate(dateString: string): string {
  // ZUGFeRD requires an IssueDateTime, so fall back to today when the caller
  // passes an empty or unparseable value (e.g. a storno PDF built from a
  // stripped-down invoice record with no invoice_date).
  const date = dateString ? new Date(dateString) : new Date();
  const safeDate = Number.isNaN(date.getTime()) ? new Date() : date;
  return safeDate.toISOString().split("T")[0].replace(/-/g, "");
}

function formatDueDate(dateString: string, daysToAdd: number): string {
  // BT-9 DueDateDateTime = invoice_date + payment_terms_reseller_in_days.
  // Use UTC ms arithmetic so DST transitions can't shift the result by a
  // day; ZUGFeRD dates are calendar-day (qualifier 102) anyway.
  const base = dateString ? new Date(dateString) : new Date();
  const safeDate = Number.isNaN(base.getTime()) ? new Date() : base;
  const due = new Date(safeDate.getTime() + daysToAdd * 86_400_000);
  return due.toISOString().split("T")[0].replace(/-/g, "");
}

// ─── XML generation ─────────────────────────────────────────────────────────

/** Emit a CII ``ApplicableProductCharacteristic`` block carrying the
 * EU 2018/848 organic status for one line item. Returns an empty
 * string for ``conventional`` / unset — those make no organic claim
 * and shouldn't appear in the machine-readable invoice. The
 * ``Description`` is the i18n label of the field itself (a constant
 * "Bio-Status" in DE); the ``Value`` is the localised status label
 * shared with the PDF + UI via ``organicStatusLabel``. */
function organicCharacteristicXml(
  status: OrganicStatus | undefined,
  t: TFunction,
): string {
  if (!status || status === "conventional") return "";
  return `
          <ram:ApplicableProductCharacteristic>
            <ram:Description>${escapeXml(
              t("commissioning.organic_status"),
            )}</ram:Description>
            <ram:Value>${escapeXml(organicStatusLabel(t, status))}</ram:Value>
          </ram:ApplicableProductCharacteristic>`;
}

/** Document-level Bio-Kontrollstelle disclosure(s).
 *
 * Mirrors the PDF footer: one note per organic mark that actually
 * appears among the line items, naming the tenant's control body.
 * Suppressed entirely when the tenant has no
 * ``organic_control_number`` (i.e. isn't certified) or when no line
 * carries a non-conventional status.
 *
 * The note text matches the PDF wording so DATEV / lexoffice / a
 * tax auditor cross-checking the e-PDF against its visual content
 * see the same string both places. */
function organicIncludedNotesXml(
  lineItems: LineItemBase[],
  controlNumber: string | null | undefined,
  t: TFunction,
): string {
  if (!controlNumber) return "";
  const { hasOrganic, hasInConversion } = organicMarksPresent(lineItems);
  if (!hasOrganic && !hasInConversion) return "";

  const notes: string[] = [];
  if (hasOrganic) {
    notes.push(
      `${t("commissioning.organic.organic_footer")}: ${controlNumber}`,
    );
  }
  if (hasInConversion) {
    notes.push(
      `${t("commissioning.organic.in_conversion_footer")}: ${controlNumber}`,
    );
  }
  return notes
    .map(
      (text) => `
    <ram:IncludedNote>
      <ram:Content>${escapeXml(text)}</ram:Content>
    </ram:IncludedNote>`,
    )
    .join("");
}

function generateLineItemsXML(
  lineItems: LineItemBase[],
  crateItems: LineItemBase[],
  t: TFunction,
  isCreditNote: boolean,
): string {
  let xml = "";
  let lineNumber = 1;
  // A storno / correction is emitted as a credit note (TypeCode 381) whose
  // amounts and quantities are POSITIVE (EN 16931 practice), while the
  // underlying records carry negated values — so take magnitudes for credit
  // notes. The unit price is never negated, so it is left untouched.
  const mag = (value: number): number =>
    isCreditNote ? Math.abs(value) : value;

  for (const item of lineItems) {
    const amount = Number(item.amount);
    const pricePerUnit = Number(item.price_per_unit);
    const discount = (amount * pricePerUnit * Number(item.rabatt || 0)) / 100;
    // Authoritative cent-rounded net from the backend (models/mixin.py),
    // not a client float recompute, so sum(lines) == TaxBasisTotalAmount
    // (BR-CO-10).
    const netAmount =
      item.line_netto != null
        ? Number(item.line_netto)
        : amount * pricePerUnit - discount;
    // Derive the line allowance from the authoritative net IN CENTS, so
    // (NetPrice × BilledQty) − Allowance == LineTotalAmount exactly under a
    // strict EN 16931 line check — instead of an independently-rounded float
    // that can drift a cent on small discounted lines.
    const allowanceCents =
      Math.round(amount * pricePerUnit * 100) - Math.round(netAmount * 100);

    xml += `
      <ram:IncludedSupplyChainTradeLineItem>
        <ram:AssociatedDocumentLineDocument>
          <ram:LineID>${lineNumber}</ram:LineID>
        </ram:AssociatedDocumentLineDocument>
        <ram:SpecifiedTradeProduct>
          <ram:Name>${escapeXml(item.share_article_name || "")}</ram:Name>${
      item.size && item.size !== "M"
        ? `
          <ram:Description>${escapeXml(t("commissioning.size"))}: ${escapeXml(item.size)}</ram:Description>`
        : ""
    }${organicCharacteristicXml(item.organic_status, t)}
        </ram:SpecifiedTradeProduct>
        <ram:SpecifiedLineTradeAgreement>
          <ram:NetPriceProductTradePrice>
            <ram:ChargeAmount>${pricePerUnit.toFixed(2)}</ram:ChargeAmount>
            <ram:BasisQuantity unitCode="${toUnEceUnitCode(item.unit)}">1</ram:BasisQuantity>
          </ram:NetPriceProductTradePrice>
        </ram:SpecifiedLineTradeAgreement>
        <ram:SpecifiedLineTradeDelivery>
          <ram:BilledQuantity unitCode="${toUnEceUnitCode(item.unit)}">${mag(amount).toFixed(3)}</ram:BilledQuantity>
        </ram:SpecifiedLineTradeDelivery>
        <ram:SpecifiedLineTradeSettlement>
          <ram:ApplicableTradeTax>
            <ram:TypeCode>VAT</ram:TypeCode>
            <ram:CategoryCode>S</ram:CategoryCode>
            <ram:RateApplicablePercent>${Number(item.tax_rate || 0).toFixed(2)}</ram:RateApplicablePercent>
          </ram:ApplicableTradeTax>${
      item.rabatt
        ? `
          <ram:SpecifiedTradeAllowanceCharge>
            <ram:ChargeIndicator>
              <udt:Indicator>false</udt:Indicator>
            </ram:ChargeIndicator>
            <ram:ActualAmount>${(mag(allowanceCents) / 100).toFixed(2)}</ram:ActualAmount>
            <ram:Reason>${escapeXml(t("commissioning.rabatt_pdf"))} ${item.rabatt}%</ram:Reason>
          </ram:SpecifiedTradeAllowanceCharge>`
        : ""
    }
          <ram:SpecifiedTradeSettlementLineMonetarySummation>
            <ram:LineTotalAmount>${mag(netAmount).toFixed(2)}</ram:LineTotalAmount>
          </ram:SpecifiedTradeSettlementLineMonetarySummation>
        </ram:SpecifiedLineTradeSettlement>
      </ram:IncludedSupplyChainTradeLineItem>`;

    lineNumber++;
  }

  for (const item of crateItems) {
    const amount = Number(item.amount);
    const pricePerUnit = Number(item.price_per_unit);
    const discount = (amount * pricePerUnit * Number(item.rabatt || 0)) / 100;
    const netAmount =
      item.line_netto != null
        ? Number(item.line_netto)
        : amount * pricePerUnit - discount;
    // See the article line above: allowance derived from the authoritative net
    // in cents so the EN 16931 line calculation balances exactly.
    const allowanceCents =
      Math.round(amount * pricePerUnit * 100) - Math.round(netAmount * 100);

    xml += `
      <ram:IncludedSupplyChainTradeLineItem>
        <ram:AssociatedDocumentLineDocument>
          <ram:LineID>${lineNumber}</ram:LineID>
        </ram:AssociatedDocumentLineDocument>
        <ram:SpecifiedTradeProduct>
          <ram:Name>${escapeXml(item.crate_type_name || "")}</ram:Name>
          <ram:Description>${escapeXml(t("commissioning.crate_deposit"))}</ram:Description>
        </ram:SpecifiedTradeProduct>
        <ram:SpecifiedLineTradeAgreement>
          <ram:NetPriceProductTradePrice>
            <ram:ChargeAmount>${pricePerUnit.toFixed(2)}</ram:ChargeAmount>
            <ram:BasisQuantity unitCode="${toUnEceUnitCode(item.unit)}">1</ram:BasisQuantity>
          </ram:NetPriceProductTradePrice>
        </ram:SpecifiedLineTradeAgreement>
        <ram:SpecifiedLineTradeDelivery>
          <ram:BilledQuantity unitCode="${toUnEceUnitCode(item.unit)}">${mag(amount).toFixed(0)}</ram:BilledQuantity>
        </ram:SpecifiedLineTradeDelivery>
        <ram:SpecifiedLineTradeSettlement>
          <ram:ApplicableTradeTax>
            <ram:TypeCode>VAT</ram:TypeCode>
            <ram:CategoryCode>S</ram:CategoryCode>
            <ram:RateApplicablePercent>${Number(item.tax_rate || 0).toFixed(2)}</ram:RateApplicablePercent>
          </ram:ApplicableTradeTax>${
      item.rabatt
        ? `
          <ram:SpecifiedTradeAllowanceCharge>
            <ram:ChargeIndicator>
              <udt:Indicator>false</udt:Indicator>
            </ram:ChargeIndicator>
            <ram:ActualAmount>${(mag(allowanceCents) / 100).toFixed(2)}</ram:ActualAmount>
            <ram:Reason>${escapeXml(t("commissioning.rabatt_pdf"))} ${item.rabatt}%</ram:Reason>
          </ram:SpecifiedTradeAllowanceCharge>`
        : ""
    }
          <ram:SpecifiedTradeSettlementLineMonetarySummation>
            <ram:LineTotalAmount>${mag(netAmount).toFixed(2)}</ram:LineTotalAmount>
          </ram:SpecifiedTradeSettlementLineMonetarySummation>
        </ram:SpecifiedLineTradeSettlement>
      </ram:IncludedSupplyChainTradeLineItem>`;

    lineNumber++;
  }

  return xml;
}

function generateTaxBreakdownXML(
  taxBreakdown: TaxBreakdownItem[],
  isCreditNote: boolean,
): string {
  const mag = (value: number): number =>
    isCreditNote ? Math.abs(value) : value;
  return taxBreakdown
    .map(
      (item) => `
      <ram:ApplicableTradeTax>
        <ram:CalculatedAmount>${mag(item.tax).toFixed(2)}</ram:CalculatedAmount>
        <ram:TypeCode>VAT</ram:TypeCode>
        <ram:BasisAmount>${mag(item.netto).toFixed(2)}</ram:BasisAmount>
        <ram:CategoryCode>S</ram:CategoryCode>
        <ram:RateApplicablePercent>${item.rate.toFixed(2)}</ram:RateApplicablePercent>
      </ram:ApplicableTradeTax>`,
    )
    .join("");
}

// ─── Main export ────────────────────────────────────────────────────────────

/**
 * Resolved payment terms for this specific invoice.
 *
 *  * ``days`` — net days from invoice_date to due_date (BT-9).
 *  * ``earlyPaymentDiscountPercent`` / ``earlyPaymentDiscountDays`` —
 *    optional Skonto. Both required to render the discount line; if
 *    either is NULL the discount block is omitted.
 *
 * Callers usually derive these via
 * ``Reseller.get_payment_terms_days()`` / ``get_early_payment_discount()``
 * on the backend, which already implements the per-reseller → tenant
 * fallback. Defaults below match the historical hardcoded values so
 * old callers keep working.
 */
export interface PaymentTerms {
  days: number;
  earlyPaymentDiscountPercent?: number | null;
  earlyPaymentDiscountDays?: number | null;
}

/**
 * Generates ZUGFeRD 2.1 / EN 16931 compliant XML for e-invoicing.
 *
 * ``currencyCode`` is the ISO 4217 alpha-3 code (``"EUR"``, ``"USD"``,
 * ``"CHF"``, …). It is emitted in the ``InvoiceCurrencyCode`` element
 * and, per CII-DT-031, as a ``currencyID`` attribute ONLY on
 * ``TaxTotalAmount`` (the one summation amount that may be stated in a
 * second tax-reporting currency) — never on the other monetary totals.
 * Defaults to ``"EUR"``.
 *
 * ``paymentTerms`` is the per-invoice resolved payment terms. When
 * omitted, falls back to the tenant default on ``tenantSettings`` —
 * also keeps the legacy single-source-of-truth flow working until
 * every caller passes a resolved object.
 */
export function generateZUGFeRDXML(
  invoiceData: ZUGFeRDInput,
  bankDetails: BankDetails,
  tenantSettings: TenantPDFSettings,
  t: TFunction,
  currencyCode: string = "EUR",
  paymentTerms?: PaymentTerms,
): string {
  const { invoice, lineItems, crateItems, taxBreakdown, totals } = invoiceData;

  // A storno / correction is a credit note: TypeCode 381, positive amounts
  // (the record carries negatives), and a BG-3 reference back to the
  // original invoice. A plain invoice stays 380 with its values as-is.
  const creditNote = isCreditNote(invoice.document_type);
  const documentTypeCode = creditNote ? "381" : "380";
  const mag = (value: number): number =>
    creditNote ? Math.abs(value) : value;

  const resolvedTerms: PaymentTerms = paymentTerms ?? {
    days: tenantSettings.payment_terms_reseller_in_days || 14,
    earlyPaymentDiscountPercent:
      tenantSettings.early_payment_discount_percent ?? null,
    earlyPaymentDiscountDays:
      tenantSettings.early_payment_discount_days ?? null,
  };
  const paymentTermsDays = resolvedTerms.days || 14;
  const skontoPct = resolvedTerms.earlyPaymentDiscountPercent;
  const skontoDays = resolvedTerms.earlyPaymentDiscountDays;
  // Render the Skonto line only when both halves are configured. A
  // percent-without-days (or vice versa) is meaningless on an invoice
  // and would confuse strict ZUGFeRD validators.
  const skontoActive =
    skontoPct != null && skontoDays != null && Number(skontoPct) > 0;
  const paymentTermsDescription = skontoActive
    ? `${t("commissioning.payment_terms_invoice_pdf", { days: paymentTermsDays })} ${t(
        "commissioning.early_payment_discount_invoice_pdf",
        {
          percent: skontoPct,
          days: skontoDays,
        },
      )}`
    : t("commissioning.payment_terms_invoice_pdf", { days: paymentTermsDays });

  return `<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice 
  xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
  xmlns:qdt="urn:un:unece:uncefact:data:standard:QualifiedDataType:100"
  xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
  xmlns:xs="http://www.w3.org/2001/XMLSchema"
  xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
  
  <rsm:ExchangedDocumentContext>
    <ram:GuidelineSpecifiedDocumentContextParameter>
      <!--
        Plain EN 16931 / Factur-X identifier. Previously we declared
        xrechnung_2.0 compliance which triggered all BR-DE-* checks
        even though we don't implement the XRechnung CIUS extensions.
        Drop the CIUS reference → just the core European standard.
      -->
      <ram:ID>urn:cen.eu:en16931:2017</ram:ID>
    </ram:GuidelineSpecifiedDocumentContextParameter>
  </rsm:ExchangedDocumentContext>
  
  <rsm:ExchangedDocument>
    <ram:ID>${escapeXml(`${invoice.prefix}-${invoice.invoice_number}`)}</ram:ID>
    <ram:TypeCode>${documentTypeCode}</ram:TypeCode>
    <ram:IssueDateTime>
      <udt:DateTimeString format="102">${formatDate(invoice.invoice_date || "")}</udt:DateTimeString>
    </ram:IssueDateTime>${
      invoice.document_hash
        ? `
    <ram:IncludedNote>
      <ram:Content>${escapeXml(invoice.document_hash)}</ram:Content>
    </ram:IncludedNote>`
        : ""
    }${organicIncludedNotesXml(
      lineItems,
      tenantSettings.organic_control_number,
      t,
    )}
  </rsm:ExchangedDocument>
  
  <rsm:SupplyChainTradeTransaction>
    ${generateLineItemsXML(lineItems, crateItems, t, creditNote)}
    
    <ram:ApplicableHeaderTradeAgreement>
      <ram:BuyerReference>${escapeXml(`${invoice.prefix}-${invoice.invoice_number}`)}</ram:BuyerReference>
      <ram:SellerTradeParty>
        <ram:Name>${escapeXml(tenantSettings.name || "")}</ram:Name>${
      // BG-6 Seller contact — required by the XRechnung CIUS (BR-DE-2).
      // EN 16931 alone doesn't require it, but emitting it makes the
      // invoice acceptable to validators that auto-apply XRechnung
      // rules. Only emitted when we actually have phone OR email to
      // put inside; empty TelephoneUniversalCommunication is invalid.
      // CII child order requires DefinedTradeContact BEFORE
      // PostalTradeAddress.
      (tenantSettings.phone_number || tenantSettings.email)
        ? `
        <ram:DefinedTradeContact>
          <ram:PersonName>${escapeXml(tenantSettings.name || "")}</ram:PersonName>${
            tenantSettings.phone_number
              ? `
          <ram:TelephoneUniversalCommunication>
            <ram:CompleteNumber>${escapeXml(tenantSettings.phone_number)}</ram:CompleteNumber>
          </ram:TelephoneUniversalCommunication>`
              : ""
          }${
            tenantSettings.email
              ? `
          <ram:EmailURIUniversalCommunication>
            <ram:URIID>${escapeXml(tenantSettings.email)}</ram:URIID>
          </ram:EmailURIUniversalCommunication>`
              : ""
          }
        </ram:DefinedTradeContact>`
        : ""
    }
        <ram:PostalTradeAddress>
          <ram:PostcodeCode>${escapeXml(tenantSettings.zip_code || "")}</ram:PostcodeCode>
          <ram:LineOne>${escapeXml(tenantSettings.address || "")}</ram:LineOne>
          <ram:CityName>${escapeXml(tenantSettings.city || "")}</ram:CityName>
          <ram:CountryID>${toIso3166Alpha2(tenantSettings.country)}</ram:CountryID>
        </ram:PostalTradeAddress>${
      tenantSettings.uid
        ? `
        <ram:SpecifiedTaxRegistration>
          <ram:ID schemeID="VA">${escapeXml(
            ensureVatPrefix(
              tenantSettings.uid,
              toIso3166Alpha2(tenantSettings.country),
            ),
          )}</ram:ID>
        </ram:SpecifiedTaxRegistration>`
        : ""
    }
      </ram:SellerTradeParty>

      <ram:BuyerTradeParty>
        <ram:Name>${escapeXml(invoice.reseller_name || "")}</ram:Name>
        <ram:PostalTradeAddress>
          <ram:PostcodeCode>${escapeXml(invoice.reseller_zip || "")}</ram:PostcodeCode>
          <ram:LineOne>${escapeXml(invoice.reseller_address || "")}</ram:LineOne>
          <ram:CityName>${escapeXml(invoice.reseller_city || "")}</ram:CityName>
          <ram:CountryID>${toIso3166Alpha2(invoice.reseller_country)}</ram:CountryID>
        </ram:PostalTradeAddress>${
      invoice.reseller_uid
        ? `
        <ram:SpecifiedTaxRegistration>
          <ram:ID schemeID="VA">${escapeXml(
            ensureVatPrefix(
              invoice.reseller_uid,
              toIso3166Alpha2(invoice.reseller_country),
            ),
          )}</ram:ID>
        </ram:SpecifiedTaxRegistration>`
        : ""
    }
      </ram:BuyerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    
    <ram:ApplicableHeaderTradeDelivery>
      <ram:ActualDeliverySupplyChainEvent>
        <ram:OccurrenceDateTime>
          <udt:DateTimeString format="102">${formatDate(invoice.invoice_date || "")}</udt:DateTimeString>
        </ram:OccurrenceDateTime>
      </ram:ActualDeliverySupplyChainEvent>
    </ram:ApplicableHeaderTradeDelivery>
    
    <ram:ApplicableHeaderTradeSettlement>
      <ram:InvoiceCurrencyCode>${currencyCode}</ram:InvoiceCurrencyCode>${
      // CII D16B enforces a strict child-element sequence here:
      //   InvoiceCurrencyCode → SpecifiedTradeSettlementPaymentMeans →
      //   ApplicableTradeTax → SpecifiedTradePaymentTerms →
      //   SpecifiedTradeSettlementHeaderMonetarySummation
      // PaymentMeans MUST appear before ApplicableTradeTax — putting it
      // at the end triggers xsd:cvc-complex-type.2.4.a in Mustang/KoSIT.
      bankDetails.iban
        ? `
      <ram:SpecifiedTradeSettlementPaymentMeans>
        <ram:TypeCode>58</ram:TypeCode>
        <ram:PayeePartyCreditorFinancialAccount>
          <ram:IBANID>${escapeXml(normalizeIban(bankDetails.iban))}</ram:IBANID>
          <ram:AccountName>${escapeXml(bankDetails.beneficiary)}</ram:AccountName>
        </ram:PayeePartyCreditorFinancialAccount>${
          bankDetails.bic
            ? `
        <ram:PayeeSpecifiedCreditorFinancialInstitution>
          <ram:BICID>${escapeXml(bankDetails.bic)}</ram:BICID>
        </ram:PayeeSpecifiedCreditorFinancialInstitution>`
            : ""
        }
      </ram:SpecifiedTradeSettlementPaymentMeans>`
        : ""
    }
      ${generateTaxBreakdownXML(taxBreakdown, creditNote)}

      <ram:SpecifiedTradePaymentTerms>
        <ram:Description>${escapeXml(paymentTermsDescription)}</ram:Description>
        <!--
          BT-9 DueDateDateTime — derived from invoice_date + tenant's
          payment_terms_reseller_in_days. Optional in EN 16931, but
          recommended: receivers that auto-schedule outgoing payments
          (DATEV, SAP, Lexware) read BT-9 directly instead of parsing
          the Description text.
        -->
        <ram:DueDateDateTime>
          <udt:DateTimeString format="102">${formatDueDate(
            invoice.invoice_date || "",
            paymentTermsDays,
          )}</udt:DateTimeString>
        </ram:DueDateDateTime>
      </ram:SpecifiedTradePaymentTerms>

      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:LineTotalAmount>${mag(totals.netto).toFixed(2)}</ram:LineTotalAmount>
        <ram:TaxBasisTotalAmount>${mag(totals.netto).toFixed(2)}</ram:TaxBasisTotalAmount>
        <ram:TaxTotalAmount currencyID="${currencyCode}">${mag(totals.tax).toFixed(2)}</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>${mag(totals.brutto).toFixed(2)}</ram:GrandTotalAmount>
        <ram:DuePayableAmount>${mag(totals.brutto).toFixed(2)}</ram:DuePayableAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>${
      // BG-3 preceding-invoice reference (BT-25): a credit note must point
      // back at the invoice it reverses so the receiver can net them.
      creditNote && invoice.cancels_invoice_number
        ? `
      <ram:InvoiceReferencedDocument>
        <ram:IssuerAssignedID>${escapeXml(String(invoice.cancels_invoice_number))}</ram:IssuerAssignedID>
      </ram:InvoiceReferencedDocument>`
        : ""
    }
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>`;
}

// ─── PDF embedding ──────────────────────────────────────────────────────────

/**
 * Embeds ZUGFeRD XML into a PDF as a file attachment (PDF/A-3 style).
 * Returns a new Blob with the XML embedded.
 */
export async function embedZUGFeRDXML(
  pdfBlob: Blob,
  xmlString: string,
): Promise<Blob> {
  const { PDFDocument, AFRelationship } = await import("pdf-lib");

  const pdfBytes = await pdfBlob.arrayBuffer();
  const pdfDoc = await PDFDocument.load(pdfBytes);

  const xmlBytes = new TextEncoder().encode(xmlString);

  await pdfDoc.attach(xmlBytes, "factur-x.xml", {
    mimeType: "text/xml",
    description: "Factur-X/ZUGFeRD e-invoice XML",
    afRelationship: AFRelationship.Alternative,
  });

  const modifiedBytes = await pdfDoc.save();
  return new Blob([modifiedBytes.buffer as ArrayBuffer], { type: "application/pdf" });
}

