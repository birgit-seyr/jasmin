/**
 * ZUGFeRD / EN 16931 structural conformance test.
 *
 * What this test DOES check
 * --------------------------
 *   - the emitted XML parses
 *   - the four required CII namespaces are declared
 *   - the document type code is "380" (commercial invoice)
 *   - the EN 16931 guideline ID is present in
 *     ``GuidelineSpecifiedDocumentContextParameter/ID``
 *   - every required EN 16931 Business Term ("BT-*") that the
 *     generator is responsible for ends up in the output:
 *
 *       BT-1   Invoice number
 *       BT-2   Issue date
 *       BT-3   Type code
 *       BT-5   Currency
 *       BT-23  Process control (= the EN 16931 guideline ID above)
 *       BT-27  Seller name
 *       BT-31  Seller VAT identifier (when tenant has a UID)
 *       BT-35  Seller address line
 *       BT-37  Seller city
 *       BT-38  Seller post code
 *       BT-40  Seller country
 *       BT-44  Buyer name
 *       BT-50  Buyer address line
 *       BT-52  Buyer city
 *       BT-53  Buyer post code
 *       BT-55  Buyer country
 *       BG-25  Invoice line group(s)
 *       BG-22  Document totals (BT-106/109/112)
 *
 * What this test does NOT check
 * -----------------------------
 *   - Full XSD validation against the official CII D16B schemas. The
 *     XSD bundle is ~100 files; running it in pure JS / browser is
 *     impractical. Use Mustang CLI for that:
 *       java -jar Mustang-CLI-*.jar --action validate --source x.pdf
 *   - Schematron BR-* business rules (e.g. BR-CO-15: invoice total
 *     equals sum of line nets). Same tool required.
 *
 * So: this test catches structural regressions (a refactor that drops
 * BT-1, a typo in a namespace) at PR time. Real conformance still
 * needs an annual Mustang run — see docs/tasks.txt §"ZUGFeRD
 * conformance validation".
 */

import { describe, expect, it } from "vitest";
import type { TFunction } from "i18next";
import {
  generateZUGFeRDXML,
} from "../zugferd";

// Minimal i18n stub — the XML generator only calls t() for line-item
// fallback names that aren't asserted here.
const t = ((key: string) => key) as unknown as TFunction;

const sampleTenant = {
  name: "Marillenhof CSA",
  address: "Hauptstraße 42",
  zip_code: "3500",
  city: "Krems",
  country: "AT",
  email: "office@marillenhof.example",
  phone_number: "+43 1 234 5678",
  uid: "ATU12345678",
  payment_terms_reseller_in_days: 14,
};

const sampleBankDetails = {
  iban: "AT12 3456 7890 1234 5678",
  bic: "RZOOAT2L",
  beneficiary: "Marillenhof CSA",
};

const sampleInvoice = {
  prefix: "RE-2026",
  invoice_number: 42,
  invoice_date: "2026-05-20",
  reseller_name: "Bio Markt Wien",
  reseller_address: "Marktplatz 1",
  reseller_zip: "1010",
  reseller_city: "Wien",
  reseller_country: "AT",
  reseller_uid: "ATU87654321",
  document_hash: "abc123def456",
  company_name: "Bio Markt GmbH",
};

const sampleInput = {
  invoice: sampleInvoice,
  lineItems: [
    {
      share_article_name: "Tomaten",
      amount: 10,
      price_per_unit: 3.5,
      unit: "KG",
      size: "M",
      tax_rate: 10,
      rabatt: 0,
      line_netto: 35,
    },
  ],
  crateItems: [],
  taxBreakdown: [{ rate: 10, netto: 35, tax: 3.5, brutto: 38.5 }],
  totals: { netto: 35, tax: 3.5, brutto: 38.5 },
};

function parse(xml: string): Document {
  const doc = new DOMParser().parseFromString(xml, "application/xml");
  // DOMParser swallows fatal errors and returns a <parsererror> doc;
  // surface it as a test failure instead of letting later assertions
  // pass against the error document.
  const parserError = doc.getElementsByTagName("parsererror")[0];
  if (parserError) {
    throw new Error(`XML did not parse:\n${parserError.textContent}`);
  }
  return doc;
}

// CII uses prefixed namespace nodes; document.querySelector won't match
// across namespaces reliably. Use getElementsByTagName with the prefixed
// name — that's what real ZUGFeRD validators do.
function findAll(doc: Document, tag: string): Element[] {
  return Array.from(doc.getElementsByTagName(tag));
}

function findFirst(doc: Document, tag: string): Element | null {
  return doc.getElementsByTagName(tag)[0] ?? null;
}

function textOf(doc: Document, tag: string): string | null {
  return findFirst(doc, tag)?.textContent?.trim() ?? null;
}

describe("ZUGFeRD / EN 16931 structural conformance", () => {
  const xml = generateZUGFeRDXML(sampleInput, sampleBankDetails, sampleTenant, t);
  const doc = parse(xml);

  it("declares the four required CII namespaces", () => {
    const root = doc.documentElement;
    expect(root.getAttribute("xmlns:rsm")).toBe(
      "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    );
    expect(root.getAttribute("xmlns:ram")).toBe(
      "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    );
    expect(root.getAttribute("xmlns:udt")).toBe(
      "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
    );
    expect(root.getAttribute("xmlns:qdt")).toBe(
      "urn:un:unece:uncefact:data:standard:QualifiedDataType:100",
    );
  });

  it("root element is rsm:CrossIndustryInvoice", () => {
    expect(doc.documentElement.tagName).toBe("rsm:CrossIndustryInvoice");
  });

  it("declares an EN 16931 guideline (BT-23 process control)", () => {
    const id = textOf(
      doc,
      "ram:GuidelineSpecifiedDocumentContextParameter",
    );
    // The guideline ID we emit references xrechnung_2.0 which is a CIUS
    // of EN 16931 — that's the legally compliant level for DE B2B.
    expect(id).not.toBeNull();
    expect(id).toContain("en16931");
  });

  it("BT-1 invoice number is set on ExchangedDocument/ID", () => {
    // Must scope to ExchangedDocument — there are many <ram:ID> nodes
    // in the doc (guideline ID, scheme IDs on tax registrations, etc.).
    const exDoc = findFirst(doc, "rsm:ExchangedDocument");
    expect(exDoc).not.toBeNull();
    const id = exDoc!.getElementsByTagName("ram:ID")[0]?.textContent?.trim();
    expect(id).toBe("RE-2026-42");
  });

  it("BT-3 type code is 380 (commercial invoice)", () => {
    const exDoc = findFirst(doc, "rsm:ExchangedDocument")!;
    expect(
      exDoc.getElementsByTagName("ram:TypeCode")[0]?.textContent?.trim(),
    ).toBe("380");
  });

  it("BT-2 issue date is in CCYYMMDD format (qualifier 102)", () => {
    const issueDate = findFirst(doc, "udt:DateTimeString");
    expect(issueDate?.getAttribute("format")).toBe("102");
    expect(issueDate?.textContent).toMatch(/^\d{8}$/);
    expect(issueDate?.textContent).toBe("20260520");
  });

  it("BG-4 Seller — name, address, country, VAT id", () => {
    const seller = findFirst(doc, "ram:SellerTradeParty");
    expect(seller).not.toBeNull();
    expect(seller!.getElementsByTagName("ram:Name")[0]?.textContent).toBe(
      "Marillenhof CSA",
    );
    const addr = seller!.getElementsByTagName("ram:PostalTradeAddress")[0];
    expect(addr.getElementsByTagName("ram:PostcodeCode")[0]?.textContent).toBe(
      "3500",
    );
    expect(addr.getElementsByTagName("ram:LineOne")[0]?.textContent).toBe(
      "Hauptstraße 42",
    );
    expect(addr.getElementsByTagName("ram:CityName")[0]?.textContent).toBe(
      "Krems",
    );
    expect(addr.getElementsByTagName("ram:CountryID")[0]?.textContent).toBe(
      "AT",
    );
    // BT-31 — VAT id under scheme "VA" (Value Added Tax). Required when
    // tenant has a UID, which the sample fixture provides.
    const vatReg = seller!.getElementsByTagName(
      "ram:SpecifiedTaxRegistration",
    )[0];
    expect(vatReg).toBeDefined();
    const vatId = vatReg.getElementsByTagName("ram:ID")[0];
    expect(vatId?.getAttribute("schemeID")).toBe("VA");
    expect(vatId?.textContent).toBe("ATU12345678");
  });

  it("BG-7 Buyer — name, address, country", () => {
    const buyer = findFirst(doc, "ram:BuyerTradeParty");
    expect(buyer).not.toBeNull();
    expect(buyer!.getElementsByTagName("ram:Name")[0]?.textContent).toBe(
      "Bio Markt Wien",
    );
    const addr = buyer!.getElementsByTagName("ram:PostalTradeAddress")[0];
    expect(addr.getElementsByTagName("ram:PostcodeCode")[0]?.textContent).toBe(
      "1010",
    );
    expect(addr.getElementsByTagName("ram:CityName")[0]?.textContent).toBe(
      "Wien",
    );
    expect(addr.getElementsByTagName("ram:CountryID")[0]?.textContent).toBe(
      "AT",
    );
  });

  it("BG-25 at least one IncludedSupplyChainTradeLineItem exists", () => {
    const lines = findAll(doc, "ram:IncludedSupplyChainTradeLineItem");
    expect(lines.length).toBeGreaterThanOrEqual(1);
  });

  it("BG-22 document totals: BT-106 net + BT-110 tax + BT-112 gross", () => {
    // ZUGFeRD names: LineTotalAmount (BT-106 / -109), TaxBasisTotalAmount,
    // TaxTotalAmount (BT-110), GrandTotalAmount (BT-112).
    const settlement = findFirst(
      doc,
      "ram:SpecifiedTradeSettlementHeaderMonetarySummation",
    );
    expect(settlement).not.toBeNull();
    expect(
      settlement!.getElementsByTagName("ram:LineTotalAmount")[0]?.textContent,
    ).toBeTruthy();
    expect(
      settlement!.getElementsByTagName("ram:TaxTotalAmount")[0]?.textContent,
    ).toBeTruthy();
    expect(
      settlement!.getElementsByTagName("ram:GrandTotalAmount")[0]?.textContent,
    ).toBeTruthy();
  });

  it("BT-106 + BT-110 = BT-112 (arithmetic sanity, BR-CO-15)", () => {
    const settlement = findFirst(
      doc,
      "ram:SpecifiedTradeSettlementHeaderMonetarySummation",
    )!;
    const net = parseFloat(
      settlement.getElementsByTagName("ram:LineTotalAmount")[0]!.textContent!,
    );
    const tax = parseFloat(
      settlement.getElementsByTagName("ram:TaxTotalAmount")[0]!.textContent!,
    );
    const gross = parseFloat(
      settlement.getElementsByTagName("ram:GrandTotalAmount")[0]!.textContent!,
    );
    // Small tolerance for half-even rounding (we use banker's rounding
    // server-side, see pdfBase.ts).
    expect(net + tax).toBeCloseTo(gross, 2);
  });

  it("BT-5 invoice currency code is declared (EUR)", () => {
    // BT-5 lives at the header level under ApplicableHeaderTradeSettlement.
    expect(textOf(doc, "ram:InvoiceCurrencyCode")).toBe("EUR");
  });

  it("TaxTotalAmount carries the currencyID attribute", () => {
    // This is the one element where the current generator emits
    // currencyID. EN 16931 requires currencyID on EVERY monetary
    // amount (see todo below).
    const tax = findFirst(doc, "ram:TaxTotalAmount");
    expect(tax?.getAttribute("currencyID")).toBe("EUR");
  });

  it("every header-summation monetary amount carries currencyID (BR-CO-25)", () => {
    // Every BT-* amount under SpecifiedTradeSettlementHeaderMonetarySummation
    // must declare its currency explicitly. Strict validators (Mustang /
    // KoSIT) reject the invoice as malformed otherwise.
    const settlement = findFirst(
      doc,
      "ram:SpecifiedTradeSettlementHeaderMonetarySummation",
    )!;
    for (const tag of [
      "ram:LineTotalAmount",
      "ram:TaxBasisTotalAmount",
      "ram:TaxTotalAmount",
      "ram:GrandTotalAmount",
      "ram:DuePayableAmount",
    ]) {
      const el = settlement.getElementsByTagName(tag)[0];
      expect(el, `${tag} must be emitted`).toBeDefined();
      expect(el.getAttribute("currencyID"), `${tag} missing currencyID`).toBe(
        "EUR",
      );
    }
  });

  describe("currencyCode parameter", () => {
    // The generator used to hardcode ``"EUR"`` in 6 places. After the
    // refactor a ``currencyCode`` parameter threads through to:
    //   * ``ram:InvoiceCurrencyCode``  (BT-5)
    //   * every ``currencyID`` attribute on header-summation amounts
    // The default stays ``"EUR"`` so non-migrated callers keep producing
    // the same payload.

    it("defaults to EUR when no currencyCode is passed (backwards compatibility)", () => {
      const defaultXml = generateZUGFeRDXML(
        sampleInput,
        sampleBankDetails,
        sampleTenant,
        t,
      );
      const defaultDoc = parse(defaultXml);
      expect(textOf(defaultDoc, "ram:InvoiceCurrencyCode")).toBe("EUR");
      expect(
        findFirst(defaultDoc, "ram:GrandTotalAmount")?.getAttribute(
          "currencyID",
        ),
      ).toBe("EUR");
    });

    it("emits the explicit currencyCode in BT-5 and every currencyID", () => {
      const usdXml = generateZUGFeRDXML(
        sampleInput,
        sampleBankDetails,
        sampleTenant,
        t,
        "USD",
      );
      const usdDoc = parse(usdXml);

      // BT-5 InvoiceCurrencyCode now reflects the caller's currency.
      expect(textOf(usdDoc, "ram:InvoiceCurrencyCode")).toBe("USD");

      // Every monetary summation amount picks up the same code.
      const settlement = findFirst(
        usdDoc,
        "ram:SpecifiedTradeSettlementHeaderMonetarySummation",
      )!;
      for (const tag of [
        "ram:LineTotalAmount",
        "ram:TaxBasisTotalAmount",
        "ram:TaxTotalAmount",
        "ram:GrandTotalAmount",
        "ram:DuePayableAmount",
      ]) {
        const el = settlement.getElementsByTagName(tag)[0];
        expect(
          el.getAttribute("currencyID"),
          `${tag} should carry the explicit USD code`,
        ).toBe("USD");
      }

      // Sanity: no stray EUR left over in the XML when the caller asked
      // for USD. (Regex covers attribute + element-text occurrences.)
      expect(usdXml).not.toMatch(/EUR/);
    });
  });

  it("BG-6 Seller contact — phone + email (BR-DE-2)", () => {
    const seller = findFirst(doc, "ram:SellerTradeParty")!;
    const contact = seller.getElementsByTagName("ram:DefinedTradeContact")[0];
    expect(contact, "DefinedTradeContact must be emitted").toBeDefined();
    expect(
      contact
        .getElementsByTagName("ram:TelephoneUniversalCommunication")[0]
        ?.getElementsByTagName("ram:CompleteNumber")[0]?.textContent,
    ).toBe("+43 1 234 5678");
    expect(
      contact
        .getElementsByTagName("ram:EmailURIUniversalCommunication")[0]
        ?.getElementsByTagName("ram:URIID")[0]?.textContent,
    ).toBe("office@marillenhof.example");
  });

  it("DefinedTradeContact comes BEFORE PostalTradeAddress (CII order)", () => {
    const seller = findFirst(doc, "ram:SellerTradeParty")!;
    const childTags = Array.from(seller.children).map((el) => el.tagName);
    const contactIdx = childTags.indexOf("ram:DefinedTradeContact");
    const addressIdx = childTags.indexOf("ram:PostalTradeAddress");
    expect(contactIdx).toBeGreaterThanOrEqual(0);
    expect(contactIdx).toBeLessThan(addressIdx);
  });

  // The setting flows tenant → pdfBase getSetting → tenantSettings DTO
  // → here. Verify the value actually lands in the EN 16931
  // ``<ram:SpecifiedTradePaymentTerms><ram:Description>`` text, with a
  // sane fallback when the tenant hasn't configured it.
  describe("BT — payment terms description carries the configured days", () => {
    // Interpolating t() — the file-level stub returns the key, which
    // would mask the ``days`` param. Here we mimic i18next's `{{var}}`
    // substitution so the assertion sees the real value. Maps the one
    // key under test to its real translation template (the stub doesn't
    // load i18n, so without this the generator would emit the bare key
    // and ``{{days}}`` would never appear to be substituted).
    const I18N_TEMPLATES: Record<string, string> = {
      "commissioning.payment_terms_invoice_pdf":
        "payment terms: payment within {{days}} days without deduction.",
    };
    const tWithDays = ((key: string, vars?: Record<string, unknown>) => {
      const template = I18N_TEMPLATES[key] ?? key;
      if (!vars) return template;
      return template.replace(/\{\{(\w+)\}\}/g, (_, name) =>
        vars[name] === undefined ? `{{${name}}}` : String(vars[name]),
      );
    }) as unknown as TFunction;

    function paymentTermsDescription(
      paymentTermsDays: number | undefined,
    ): string | null {
      const tenant = { ...sampleTenant, payment_terms_reseller_in_days: paymentTermsDays };
      const xml = generateZUGFeRDXML(sampleInput, sampleBankDetails, tenant, tWithDays);
      const localDoc = parse(xml);
      const terms = findFirst(localDoc, "ram:SpecifiedTradePaymentTerms");
      return terms?.getElementsByTagName("ram:Description")[0]?.textContent ?? null;
    }

    it("propagates the configured value (30) into the Description", () => {
      const description = paymentTermsDescription(30);
      expect(description).not.toBeNull();
      expect(description).toContain("30");
      // Defensive: the default fallback must NOT have leaked.
      expect(description).not.toContain("14");
    });

    it("falls back to 14 days when the tenant has not configured a value", () => {
      // ``payment_terms_reseller_in_days`` is optional on TenantPDFSettings;
      // the generator's ``|| 14`` guard backs it. If a tenant ever ships
      // without it (anonymous bootstrap, brand-new tenant before the
      // overlay is materialised, …) the invoice must still produce
      // legally sensible terms instead of "payment within undefined days".
      expect(paymentTermsDescription(undefined)).toContain("14");
    });

    it("placement: Description lives inside SpecifiedTradePaymentTerms (BG-26)", () => {
      // Validators (Mustang, KoSIT) reject ``ram:Description`` text in any
      // other position under ApplicableHeaderTradeSettlement. Guard
      // against a refactor that hoists it out by accident.
      const xml = generateZUGFeRDXML(
        sampleInput,
        sampleBankDetails,
        { ...sampleTenant, payment_terms_reseller_in_days: 21 },
        tWithDays,
      );
      const localDoc = parse(xml);
      const terms = findFirst(localDoc, "ram:SpecifiedTradePaymentTerms");
      expect(terms).not.toBeNull();
      const description = terms!.getElementsByTagName("ram:Description")[0];
      expect(description?.parentElement?.tagName).toBe(
        "ram:SpecifiedTradePaymentTerms",
      );
    });

    // ── Per-invoice payment-term override ──────────────────────────
    //
    // The ``paymentTerms`` parameter wins over the tenant default. This
    // is the path the InvoicePDFGenerator uses for per-reseller terms
    // (the backend serializer resolves the per-reseller → tenant
    // fallback, so the generator passes concrete numbers).
    it("paymentTerms override wins over tenant default for the days value", () => {
      const I18N_TEMPLATES_LOCAL: Record<string, string> = {
        "commissioning.payment_terms_invoice_pdf":
          "payment terms: payment within {{days}} days without deduction.",
      };
      const tLocal = ((key: string, vars?: Record<string, unknown>) => {
        const template = I18N_TEMPLATES_LOCAL[key] ?? key;
        if (!vars) return template;
        return template.replace(/\{\{(\w+)\}\}/g, (_, name) =>
          vars[name] === undefined ? `{{${name}}}` : String(vars[name]),
        );
      }) as unknown as TFunction;

      const xml = generateZUGFeRDXML(
        sampleInput,
        sampleBankDetails,
        { ...sampleTenant, payment_terms_reseller_in_days: 14 }, // tenant says 14
        tLocal,
        "EUR",
        { days: 45 }, // reseller override says 45
      );
      const localDoc = parse(xml);
      const desc = findFirst(localDoc, "ram:SpecifiedTradePaymentTerms")
        ?.getElementsByTagName("ram:Description")[0]?.textContent;
      expect(desc).toContain("45");
      expect(desc).not.toContain("14");

      // BT-9 DueDateDateTime also reflects the override.
      const due = findFirst(localDoc, "ram:DueDateDateTime")
        ?.getElementsByTagName("udt:DateTimeString")[0]?.textContent;
      // sampleInput's invoice_date is 2026-05-20; +45 days → 2026-07-04.
      expect(due).toBe("20260704");
    });

    it("appends Skonto sentence when paymentTerms carries both discount fields", () => {
      const I18N_TEMPLATES_LOCAL: Record<string, string> = {
        "commissioning.payment_terms_invoice_pdf":
          "payment terms: payment within {{days}} days without deduction.",
        "commissioning.early_payment_discount_invoice_pdf":
          "{{percent}}% Skonto bei Zahlung innerhalb {{days}} Tagen.",
      };
      const tLocal = ((key: string, vars?: Record<string, unknown>) => {
        const template = I18N_TEMPLATES_LOCAL[key] ?? key;
        if (!vars) return template;
        return template.replace(/\{\{(\w+)\}\}/g, (_, name) =>
          vars[name] === undefined ? `{{${name}}}` : String(vars[name]),
        );
      }) as unknown as TFunction;

      const xml = generateZUGFeRDXML(
        sampleInput,
        sampleBankDetails,
        sampleTenant,
        tLocal,
        "EUR",
        {
          days: 30,
          earlyPaymentDiscountPercent: 2,
          earlyPaymentDiscountDays: 7,
        },
      );
      const desc = findFirst(parse(xml), "ram:SpecifiedTradePaymentTerms")
        ?.getElementsByTagName("ram:Description")[0]?.textContent;
      expect(desc).toContain("30");
      expect(desc).toContain("2");
      expect(desc).toContain("7");
      expect(desc).toContain("Skonto");
    });

    it("omits Skonto sentence when only one of the discount fields is set", () => {
      const I18N_TEMPLATES_LOCAL: Record<string, string> = {
        "commissioning.payment_terms_invoice_pdf":
          "payment terms: payment within {{days}} days without deduction.",
        "commissioning.early_payment_discount_invoice_pdf":
          "{{percent}}% Skonto bei Zahlung innerhalb {{days}} Tagen.",
      };
      const tLocal = ((key: string, vars?: Record<string, unknown>) => {
        const template = I18N_TEMPLATES_LOCAL[key] ?? key;
        if (!vars) return template;
        return template.replace(/\{\{(\w+)\}\}/g, (_, name) =>
          vars[name] === undefined ? `{{${name}}}` : String(vars[name]),
        );
      }) as unknown as TFunction;

      // ``percent`` set but ``days`` NULL → no Skonto line.
      const xml = generateZUGFeRDXML(
        sampleInput,
        sampleBankDetails,
        sampleTenant,
        tLocal,
        "EUR",
        {
          days: 14,
          earlyPaymentDiscountPercent: 2,
          earlyPaymentDiscountDays: null,
        },
      );
      const desc = findFirst(parse(xml), "ram:SpecifiedTradePaymentTerms")
        ?.getElementsByTagName("ram:Description")[0]?.textContent;
      expect(desc).not.toContain("Skonto");
    });

    it("omits Skonto sentence when percent is 0 (treated as 'no discount offered')", () => {
      const I18N_TEMPLATES_LOCAL: Record<string, string> = {
        "commissioning.payment_terms_invoice_pdf":
          "payment terms: payment within {{days}} days without deduction.",
        "commissioning.early_payment_discount_invoice_pdf":
          "{{percent}}% Skonto bei Zahlung innerhalb {{days}} Tagen.",
      };
      const tLocal = ((key: string, vars?: Record<string, unknown>) => {
        const template = I18N_TEMPLATES_LOCAL[key] ?? key;
        if (!vars) return template;
        return template.replace(/\{\{(\w+)\}\}/g, (_, name) =>
          vars[name] === undefined ? `{{${name}}}` : String(vars[name]),
        );
      }) as unknown as TFunction;

      const xml = generateZUGFeRDXML(
        sampleInput,
        sampleBankDetails,
        sampleTenant,
        tLocal,
        "EUR",
        {
          days: 14,
          earlyPaymentDiscountPercent: 0,
          earlyPaymentDiscountDays: 7,
        },
      );
      const desc = findFirst(parse(xml), "ram:SpecifiedTradePaymentTerms")
        ?.getElementsByTagName("ram:Description")[0]?.textContent;
      expect(desc).not.toContain("Skonto");
    });
  });

  // BT-9 DueDateDateTime is what auto-scheduling receivers (DATEV, SAP,
  // Lexware) actually read. The Description text is there for humans
  // and for receivers that don't process BT-9. We emit both.
  describe("BT-9 DueDateDateTime — machine-readable due date", () => {
    const tWithDays = ((key: string, vars?: Record<string, unknown>) => {
      if (!vars) return key;
      return key.replace(/\{\{(\w+)\}\}/g, (_, name) =>
        vars[name] === undefined ? `{{${name}}}` : String(vars[name]),
      );
    }) as unknown as TFunction;

    function dueDate(
      paymentTermsDays: number | undefined,
      invoiceDate: string,
    ): string | null {
      const tenant = { ...sampleTenant, payment_terms_reseller_in_days: paymentTermsDays };
      const input = {
        ...sampleInput,
        invoice: { ...sampleInvoice, invoice_date: invoiceDate },
      };
      const xml = generateZUGFeRDXML(input, sampleBankDetails, tenant, tWithDays);
      const localDoc = parse(xml);
      const terms = findFirst(localDoc, "ram:SpecifiedTradePaymentTerms");
      const due = terms?.getElementsByTagName("ram:DueDateDateTime")[0];
      const dt = due?.getElementsByTagName("udt:DateTimeString")[0];
      return dt?.textContent ?? null;
    }

    it("emits DueDateDateTime as invoice_date + configured days", () => {
      // 2026-05-20 + 30 days = 2026-06-19.
      expect(dueDate(30, "2026-05-20")).toBe("20260619");
    });

    it("crosses month boundaries correctly", () => {
      // 2026-05-20 + 14 days = 2026-06-03.
      expect(dueDate(14, "2026-05-20")).toBe("20260603");
    });

    it("crosses year boundaries correctly", () => {
      // 2026-12-20 + 14 days = 2027-01-03.
      expect(dueDate(14, "2026-12-20")).toBe("20270103");
    });

    it("falls back to 14 days when the tenant has not configured a value", () => {
      // ``|| 14`` fallback in the generator must also drive BT-9, not
      // just the Description text. Otherwise a fresh tenant ships
      // invoices where the human text says "14 days" but BT-9 is
      // missing — DATEV would book it as immediately due.
      expect(dueDate(undefined, "2026-05-20")).toBe("20260603");
    });

    it("uses qualifier 102 (CCYYMMDD) like BT-2 IssueDateTime", () => {
      const xml = generateZUGFeRDXML(
        { ...sampleInput, invoice: { ...sampleInvoice, invoice_date: "2026-05-20" } },
        sampleBankDetails,
        { ...sampleTenant, payment_terms_reseller_in_days: 30 },
        tWithDays,
      );
      const localDoc = parse(xml);
      const due = findFirst(localDoc, "ram:DueDateDateTime");
      const dt = due?.getElementsByTagName("udt:DateTimeString")[0];
      expect(dt?.getAttribute("format")).toBe("102");
      expect(dt?.textContent).toMatch(/^\d{8}$/);
    });

    it("placement: DueDateDateTime lives inside SpecifiedTradePaymentTerms AFTER Description (CII order)", () => {
      const xml = generateZUGFeRDXML(
        { ...sampleInput, invoice: { ...sampleInvoice, invoice_date: "2026-05-20" } },
        sampleBankDetails,
        { ...sampleTenant, payment_terms_reseller_in_days: 30 },
        tWithDays,
      );
      const localDoc = parse(xml);
      const terms = findFirst(localDoc, "ram:SpecifiedTradePaymentTerms")!;
      const due = terms.getElementsByTagName("ram:DueDateDateTime")[0];
      expect(due?.parentElement?.tagName).toBe("ram:SpecifiedTradePaymentTerms");
      // CII order: Description → DueDateDateTime.
      const childTags = Array.from(terms.children).map((c) => c.tagName);
      const descriptionIdx = childTags.indexOf("ram:Description");
      const dueIdx = childTags.indexOf("ram:DueDateDateTime");
      expect(descriptionIdx).toBeGreaterThanOrEqual(0);
      expect(dueIdx).toBeGreaterThan(descriptionIdx);
    });
  });

  // CII D16B enforces a strict child-element sequence inside
  // ApplicableHeaderTradeSettlement. Placing children out of order
  // triggers xsd:cvc-complex-type.2.4.a in Mustang/KoSIT — exactly
  // the error we just hit on the external validator. A structural
  // test like this one would miss it without an explicit ordering
  // assertion, so we add one here.
  it("ApplicableHeaderTradeSettlement children are in CII order", () => {
    const settlement = findFirst(doc, "ram:ApplicableHeaderTradeSettlement")!;
    const childTags = Array.from(settlement.children).map((el) => el.tagName);
    // Required CII order (subset we actually emit):
    //   InvoiceCurrencyCode
    //   SpecifiedTradeSettlementPaymentMeans?   (only when IBAN set)
    //   ApplicableTradeTax+
    //   SpecifiedTradePaymentTerms?
    //   SpecifiedTradeSettlementHeaderMonetarySummation
    const must = [
      "ram:InvoiceCurrencyCode",
      "ram:SpecifiedTradeSettlementPaymentMeans",
      "ram:ApplicableTradeTax",
      "ram:SpecifiedTradePaymentTerms",
      "ram:SpecifiedTradeSettlementHeaderMonetarySummation",
    ];
    const positions = must
      .map((tag) => ({ tag, idx: childTags.indexOf(tag) }))
      .filter((p) => p.idx >= 0);
    for (let k = 1; k < positions.length; k++) {
      expect(
        positions[k].idx,
        `${positions[k].tag} must come after ${positions[k - 1].tag}`,
      ).toBeGreaterThan(positions[k - 1].idx);
    }
  });
});

describe("EN 16931 line calculation (FIN-1 / FIN-2)", () => {
  // A small discounted line where the OLD float-recomputed allowance drifts a
  // cent from the authoritative net: amount 1 × 0.10, 25% rabatt → gross 0.10,
  // net 0.08 (the backend rounds 0.075 up). Float discount = 0.025 → "0.03",
  // and 0.10 − 0.03 = 0.07 ≠ 0.08; the cent-derived allowance is 0.02.
  const discountedInput = {
    ...sampleInput,
    lineItems: [
      {
        share_article_name: "Kräuter",
        amount: 1,
        price_per_unit: 0.1,
        unit: "KG",
        size: "M",
        tax_rate: 10,
        rabatt: 25,
        line_netto: 0.08,
      },
    ],
    taxBreakdown: [{ rate: 10, netto: 0.08, tax: 0.008, brutto: 0.088 }],
    totals: { netto: 0.08, tax: 0.01, brutto: 0.09 },
  };
  const xml = generateZUGFeRDXML(
    discountedInput,
    sampleBankDetails,
    sampleTenant,
    t,
  );
  const line = findFirst(parse(xml), "ram:IncludedSupplyChainTradeLineItem")!;
  const num = (el: Element, tag: string) =>
    Number(el.getElementsByTagName(tag)[0]!.textContent);

  it("FIN-1: NetPrice BasisQuantity is 1 (price applies per single unit)", () => {
    const netPrice = line.getElementsByTagName(
      "ram:NetPriceProductTradePrice",
    )[0]!;
    expect(
      netPrice.getElementsByTagName("ram:BasisQuantity")[0]!.textContent,
    ).toBe("1");
  });

  it("FIN-2: NetPrice × BilledQty − Allowance == LineTotalAmount (BR-CO-10)", () => {
    const netPrice = num(line, "ram:ChargeAmount");
    const billed = num(line, "ram:BilledQuantity");
    const allowance = num(line, "ram:ActualAmount");
    const lineTotal = num(line, "ram:LineTotalAmount");

    // The cent-derived allowance keeps the EN 16931 line identity exact...
    expect(netPrice * billed - allowance).toBeCloseTo(lineTotal, 2);
    // ...at the authoritative values (0.02 allowance, 0.08 net — not the
    // 0.03/0.07 the old float recompute produced).
    expect(allowance).toBeCloseTo(0.02, 2);
    expect(lineTotal).toBeCloseTo(0.08, 2);
  });
});

describe("DOC-5: weight-based article line keeps full 3-decimal BilledQuantity", () => {
  const input = {
    ...sampleInput,
    lineItems: [
      {
        share_article_name: "Tomaten",
        amount: 1.255, // 3-decimal KG weight (model DecimalField decimal_places=3)
        price_per_unit: 2.0,
        unit: "KG",
        size: "M",
        tax_rate: 10,
        rabatt: 0,
        line_netto: 2.51, // round(1.255 * 2.00, 2)
      },
    ],
    taxBreakdown: [{ rate: 10, netto: 2.51, tax: 0.25, brutto: 2.76 }],
    totals: { netto: 2.51, tax: 0.25, brutto: 2.76 },
  };
  const doc = parse(generateZUGFeRDXML(input, sampleBankDetails, sampleTenant, t));
  const line = findFirst(doc, "ram:IncludedSupplyChainTradeLineItem")!;
  const lineText = (tag: string) =>
    line.getElementsByTagName(tag)[0]?.textContent?.trim() ?? "";

  it("BilledQuantity preserves the third decimal (was truncated to 1.25)", () => {
    expect(lineText("ram:BilledQuantity")).toBe("1.255");
  });

  it("EN 16931 line identity balances (BR-CO-10: NetPrice×Qty − Allowance == LineTotal)", () => {
    const netPrice = Number(lineText("ram:ChargeAmount"));
    const qty = Number(lineText("ram:BilledQuantity"));
    const allowance = Number(lineText("ram:ActualAmount") || "0");
    const lineTotal = Number(lineText("ram:LineTotalAmount"));
    expect(Math.abs(netPrice * qty - allowance - lineTotal)).toBeLessThan(0.005);
  });
});
