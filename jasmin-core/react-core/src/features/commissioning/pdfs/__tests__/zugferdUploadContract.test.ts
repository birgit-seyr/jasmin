/**
 * The e-invoice XML the generator writes, held to the checks the finalized
 * invoice upload runs on it.
 *
 * The office's browser uploads this XML together with the invoice PDF, and the
 * backend upload validator (apps/commissioning/services/einvoice_upload.py)
 * enforces the same rules as ``uploadCheckFailures`` below: it refuses both
 * files unless the XML parses without a DTD, its root is the CII invoice, no
 * processing instruction names a stylesheet, and no element or attribute sits
 * in the XHTML, SVG, MathML or XLink namespace. A generator change that breaks
 * one of them would stop every invoice upload, so the real output is checked
 * here — an invoice, a credit note, and both with awkward text.
 */

import { describe, expect, it } from "vitest";
import type { TFunction } from "i18next";
import { DocumentTypeEnum } from "@shared/api/generated/models";
import { generateZUGFeRDXML } from "../zugferd";

type GeneratorInput = Parameters<typeof generateZUGFeRDXML>[0];
type LineItem = GeneratorInput["lineItems"][number];

const CII_INVOICE_NAMESPACE =
  "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100";

/** Whether a browser runs script from ``namespace`` in an XML document: the
 *  same four namespaces as ``_ACTIVE_CONTENT_NAMESPACES`` in the backend
 *  upload validator. */
function isActiveContentNamespace(namespace: string | null): boolean {
  return [
    "http://www.w3.org/1999/xhtml",
    "http://www.w3.org/2000/svg",
    "http://www.w3.org/1998/Math/MathML",
    "http://www.w3.org/1999/xlink",
  ].includes(namespace ?? "");
}

/**
 * The upload checks ``xml`` fails, in the backend's wording; empty when the
 * upload stores it. Like the backend, it refuses a processing instruction only
 * when it names a stylesheet, in any case and wherever it sits. The XML
 * declaration is no processing instruction, in the DOM as for the backend's
 * parser.
 */
function uploadCheckFailures(xml: string): string[] {
  const doc = new DOMParser().parseFromString(xml, "application/xml");
  if (doc.getElementsByTagName("parsererror").length > 0) {
    return ["is not well-formed"];
  }
  const failures = new Set<string>();
  if (doc.doctype !== null) failures.add("carries a DTD");
  const root = doc.documentElement;
  if (
    root.namespaceURI !== CII_INVOICE_NAMESPACE ||
    root.localName !== "CrossIndustryInvoice"
  ) {
    failures.add("is not a CII invoice");
  }
  const walker = doc.createTreeWalker(
    doc,
    NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_PROCESSING_INSTRUCTION,
  );
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node.nodeType === Node.PROCESSING_INSTRUCTION_NODE) {
      const { target } = node as ProcessingInstruction;
      if (target.toLowerCase() === "xml-stylesheet") {
        failures.add("references a stylesheet");
      }
    } else {
      const element = node as Element;
      const namespaces = [
        element.namespaceURI,
        ...Array.from(element.attributes, (attribute) => attribute.namespaceURI),
      ];
      if (namespaces.some(isActiveContentNamespace)) {
        failures.add("carries XHTML, SVG, MathML or XLink");
      }
    }
  }
  return [...failures];
}

// The generator's translated strings are their keys here.
const t = ((key: string) => key) as unknown as TFunction;

// Every optional block the generator writes is switched on: the seller's
// contact, both VAT ids, a BIC, early-payment discount terms, the organic notes
// and line characteristics, a sized line, discounts and a crate deposit line.
const tenant = {
  name: "Marillenhof CSA",
  address: "Main Street 42",
  zip_code: "3500",
  city: "Krems",
  country: "AT",
  email: "office@marillenhof.example",
  phone_number: "+43 1 234 5678",
  uid: "ATU12345678",
  payment_terms_reseller_in_days: 14,
  early_payment_discount_percent: 2,
  early_payment_discount_days: 7,
  organic_control_number: "AT-BIO-301",
};

const bankDetails = {
  iban: "AT12 3456 7890 1234 5678",
  bic: "RZOOAT2L",
  beneficiary: "Marillenhof CSA",
};

const invoiceInput: GeneratorInput = {
  invoice: {
    prefix: "RE-2026",
    invoice_number: 42,
    invoice_date: "2026-05-20",
    reseller_name: "Organic Market Vienna",
    reseller_address: "Market Square 1",
    reseller_zip: "1010",
    reseller_city: "Vienna",
    reseller_country: "AT",
    reseller_uid: "ATU87654321",
    document_hash: "abc123def456",
    document_type: DocumentTypeEnum.invoice,
  },
  lineItems: [
    {
      share_article_name: "Tomatoes",
      amount: 10,
      price_per_unit: 3.5,
      unit: "KG",
      size: "L",
      tax_rate: 10,
      rabatt: 10,
      line_netto: 31.5,
      organic_status: "organic",
    },
    {
      share_article_name: "Carrots",
      amount: 4,
      price_per_unit: 2,
      unit: "BUND",
      size: "M",
      tax_rate: 10,
      rabatt: 0,
      line_netto: 8,
      organic_status: "in_conversion",
    },
  ],
  crateItems: [
    {
      crate_type_name: "Vegetable crate",
      amount: 2,
      price_per_unit: 5,
      unit: "PCS",
      tax_rate: 20,
      rabatt: 10,
      line_netto: 9,
    },
  ],
  taxBreakdown: [
    { rate: 10, netto: 39.5, tax: 3.95, brutto: 43.45 },
    { rate: 20, netto: 9, tax: 1.8, brutto: 10.8 },
  ],
  totals: { netto: 48.5, tax: 5.75, brutto: 54.25 },
};

const negated = (item: LineItem): LineItem => ({
  ...item,
  amount: -Number(item.amount),
  line_netto: -Number(item.line_netto),
});

// The storno of the invoice above: a credit note, whose record carries the
// invoice's values negated.
const creditNoteInput: GeneratorInput = {
  invoice: {
    ...invoiceInput.invoice,
    invoice_number: 43,
    document_type: DocumentTypeEnum.storno,
    cancels_invoice_number: "RE-2026-42",
  },
  lineItems: invoiceInput.lineItems.map(negated),
  crateItems: invoiceInput.crateItems.map(negated),
  taxBreakdown: invoiceInput.taxBreakdown.map((group) => ({
    rate: group.rate,
    netto: -group.netto,
    tax: -group.tax,
    brutto: -group.brutto,
  })),
  totals: { netto: -48.5, tax: -5.75, brutto: -54.25 },
};

// Quotes, an ampersand, angle brackets, umlauts and an eszett, and markup that
// has to stay text: unescaped, it would break the XML, or add a stylesheet
// instruction and an XHTML element.
const AWKWARD_TEXT =
  `"Müller" & 'Weiß' <Mödling> ]]> <!DOCTYPE x> <?xml-stylesheet href="#x"?> ` +
  `<h:p xmlns:h="http://www.w3.org/1999/xhtml" onclick="alert(1)">x</h:p>`;

// What XML forbids even escaped, and the generator drops: C0 controls, U+FFFE,
// U+FFFF and unpaired surrogates (a low one first, a high one last, so neither
// pairs with its neighbour).
const XML_FORBIDDEN_CHARACTERS =
  "\uDC00\u0000\u0001\u0008\u000B\u000C\u001F￾￿\uD800";

const awkward = (text?: string | null) =>
  `${text ?? ""} ${AWKWARD_TEXT}${XML_FORBIDDEN_CHARACTERS}`;

/** ``input`` with the awkward text in every free-text value the generator
 *  writes from it. */
function withAwkwardText(input: GeneratorInput): GeneratorInput {
  const { invoice } = input;
  return {
    ...input,
    invoice: {
      ...invoice,
      prefix: awkward(invoice.prefix),
      reseller_name: awkward(invoice.reseller_name),
      reseller_address: awkward(invoice.reseller_address),
      reseller_zip: awkward(invoice.reseller_zip),
      reseller_city: awkward(invoice.reseller_city),
      reseller_uid: awkward(invoice.reseller_uid),
      document_hash: awkward(invoice.document_hash),
      cancels_invoice_number: awkward(invoice.cancels_invoice_number),
    },
    lineItems: input.lineItems.map((item) => ({
      ...item,
      share_article_name: awkward(item.share_article_name),
      size: awkward(item.size),
    })),
    crateItems: input.crateItems.map((item) => ({
      ...item,
      crate_type_name: awkward(item.crate_type_name),
    })),
  };
}

const awkwardTenant = {
  ...tenant,
  name: awkward(tenant.name),
  address: awkward(tenant.address),
  zip_code: awkward(tenant.zip_code),
  city: awkward(tenant.city),
  email: awkward(tenant.email),
  phone_number: awkward(tenant.phone_number),
  uid: awkward(tenant.uid),
  organic_control_number: awkward(tenant.organic_control_number),
};

const awkwardBankDetails = {
  iban: awkward(bankDetails.iban),
  bic: awkward(bankDetails.bic),
  beneficiary: awkward(bankDetails.beneficiary),
};

// Every translation the generator writes carries the awkward text too.
const awkwardT = ((key: string) => awkward(key)) as unknown as TFunction;

const generatedXml = (input: GeneratorInput) =>
  generateZUGFeRDXML(input, bankDetails, tenant, t);

const generatedAwkwardXml = (input: GeneratorInput) =>
  generateZUGFeRDXML(
    withAwkwardText(input),
    awkwardBankDetails,
    awkwardTenant,
    awkwardT,
  );

describe("ZUGFeRD XML against the e-invoice upload checks", () => {
  it.each([
    ["an invoice", () => generatedXml(invoiceInput)],
    ["a credit note", () => generatedXml(creditNoteInput)],
    ["an invoice with awkward text", () => generatedAwkwardXml(invoiceInput)],
    [
      "a credit note with awkward text",
      () => generatedAwkwardXml(creditNoteInput),
    ],
  ])("passes them for %s", (_document, generate) => {
    expect(uploadCheckFailures(generate())).toEqual([]);
  });

  it("keeps awkward text as text, without the characters XML forbids", () => {
    const doc = new DOMParser().parseFromString(
      generatedAwkwardXml(creditNoteInput),
      "application/xml",
    );

    const textOf = (tagName: string) =>
      doc.getElementsByTagName(tagName)[0]?.textContent;
    expect(textOf("ram:AccountName")).toBe(`Marillenhof CSA ${AWKWARD_TEXT}`);
    // Written for a credit note only, so this also shows it is one.
    expect(textOf("ram:IssuerAssignedID")).toBe(`RE-2026-42 ${AWKWARD_TEXT}`);
  });

  // Each change below turns the generator's real output into XML the upload
  // refuses, and shows the matching check in ``uploadCheckFailures`` fails.
  const xml = generatedXml(invoiceInput);
  const inExchangedDocument = (markup: string) =>
    xml.replace("</rsm:ExchangedDocument>", `${markup}</rsm:ExchangedDocument>`);

  it.each([
    [
      "a line break before the XML declaration",
      `\n${xml}`,
      "is not well-formed",
    ],
    [
      "a DTD",
      xml.replace("?>", "?>\n<!DOCTYPE rsm:CrossIndustryInvoice>"),
      "carries a DTD",
    ],
    [
      "another root",
      xml.replace(CII_INVOICE_NAMESPACE, "urn:example:invoice"),
      "is not a CII invoice",
    ],
    [
      "a stylesheet processing instruction",
      xml.replace(
        "?>",
        '?>\n<?xml-stylesheet type="text/xsl" href="#transform"?>',
      ),
      "references a stylesheet",
    ],
    [
      "an XHTML note",
      inExchangedDocument(
        '<h:p xmlns:h="http://www.w3.org/1999/xhtml">note</h:p>',
      ),
      "carries XHTML, SVG, MathML or XLink",
    ],
    [
      "an SVG element",
      inExchangedDocument('<svg xmlns="http://www.w3.org/2000/svg"/>'),
      "carries XHTML, SVG, MathML or XLink",
    ],
    [
      "a MathML element",
      inExchangedDocument('<math xmlns="http://www.w3.org/1998/Math/MathML"/>'),
      "carries XHTML, SVG, MathML or XLink",
    ],
    [
      "an XLink attribute",
      xml.replace(
        "<ram:TypeCode>",
        '<ram:TypeCode xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="#x">',
      ),
      "carries XHTML, SVG, MathML or XLink",
    ],
  ])("fails them for the output with %s", (_change, changedXml, failure) => {
    expect(uploadCheckFailures(changedXml)).toEqual([failure]);
  });
});
