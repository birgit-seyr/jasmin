/**
 * @vitest-environment node
 *
 * PDF tests need Node's native Blob (which has .arrayBuffer()). jsdom's
 * Blob does not implement it, so we override the global vitest env for
 * this file only.
 */
import { pdf } from "@react-pdf/renderer";
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it, vi } from "vitest";
import type { DeliveryNotePDFData } from "../DeliveryNotePDF";
import DeliveryNotePDF from "../DeliveryNotePDF";
import type { InvoicePDFData } from "../InvoicePDF";
import InvoicePDF from "../InvoicePDF";
import type { OfferPDFData } from "../OfferPDF";
import OfferPDF from "../OfferPDF";
import { computeTaxBreakdown, type LineItemBase } from "../pdfBase";
import {
  SAMPLE_DELIVERY_NOTE_LINE_SETTINGS,
  SAMPLE_FOOTER_SETTINGS,
  SAMPLE_INVOICE_LINE_SETTINGS,
  SAMPLE_OFFER_LINE_SETTINGS,
  SAMPLE_TENANT_SETTINGS,
} from "../sampleResellerDocText";

// ─── Mocks ──────────────────────────────────────────────────────────────────

// ─── German translations for PDF labels ─────────────────────────────────────

const DE_TRANSLATIONS: Record<string, string> = {
  // commissioning keys used in PDFs
  "commissioning.invoice": "Rechnung",
  "commissioning.invoice_number_pdf": "Rechnungs-Nr.: ",
  "commissioning.invoice_date": "Rechnungsdatum: ",
  "commissioning.corresponding_delivery_notes": "Zugehörige Lieferscheine: ",
  "commissioning.delivery_note": "Lieferschein",
  "commissioning.delivery_note_number": "Lieferschein-Nr.: ",
  "commissioning.delivery_note_date": "Lieferschein-Datum: ",
  "commissioning.offer": "Angebot",
  "commissioning.share_article_name": "Artikel",
  "commissioning.amount": "Menge",
  "commissioning.unit": "Einheit",
  "commissioning.price_per_unit": "Preis pro Einheit",
  "commissioning.price_per_unit_invoice_pdf": "Preis/Einheit",
  "commissioning.rabatt_pdf": "Rabatt",
  "commissioning.line_netto": "Zeilensumme netto",
  "commissioning.ust": "USt.",
  "commissioning.date": "Datum",
  "commissioning.size": "Größe",
  "commissioning.sort": "Sorte",
  "commissioning.description": "Beschreibung",
  "commissioning.amount_per_pu": "Menge pro VPE",
  "commissioning.ordering_amount_in_pu": "Bestellmenge\nin VPE",
  "commissioning.pu": "VPE",
  "commissioning.KW": "KW",
  "commissioning.download_pdf": "PDF",
  "commissioning.piece_short": "Stk.",
  "commissioning.small": "klein",
  "commissioning.medium": "mittel",
  "commissioning.large": "groß",
  "commissioning.price": "Preis",
  "commissioning.netto": "Netto",
  "commissioning.brutto": "Brutto",
  "commissioning.tax": "MwSt.",
  "commissioning.total": "Gesamt",
  "commissioning.total_netto": "Gesamtbetrag netto",
  "commissioning.total_brutto": "Gesamtbetrag brutto",
  "commissioning.total_tax": "MwSt. gesamt",
  "commissioning.tax_rate": "Steuersatz",
  "commissioning.subtotal": "Zwischensumme",
  "commissioning.document_hash": "Dokument-Hash",
  "commissioning.finalized_at": "Finalisiert am",
  "commissioning.corresponding_order": "Zugehörige Bestellung: ",
  // units
  "commissioning.units.kg": "kg",
  "commissioning.units.pcs": "Stk",
  "commissioning.units.bunch": "Bund",
  // common
  "common.error": "Fehler",
};

/** Translation mock that resolves German values, with interpolation support. */
const t = ((key: string, options?: Record<string, unknown>) => {
  let value = DE_TRANSLATIONS[key] ?? key;
  // Basic interpolation: replace {{var}} placeholders
  if (options) {
    for (const [k, v] of Object.entries(options)) {
      value = value.replace(
        new RegExp(`\\{\\{\\s*${k}\\s*\\}\\}`, "g"),
        String(v),
      );
    }
  }
  return value;
}) as unknown as import("i18next").TFunction;

// Mock useUnitOptions / useSizeOptions hooks used by OfferPDF
const unitLabelMap: Record<string, string> = {
  KG: "kg",
  PCS: "Stk",
  BUNCH: "Bund",
};
const sizeLabelMap: Record<string, string> = {
  S: "klein",
  M: "mittel",
  L: "groß",
};

vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({ tenant: {} });
  return {
    useUnitOptions: () => ({
      UNIT_OPTIONS: { KG: "KG", PCS: "PCS", BUNCH: "BUNCH" },
      unitOptions: [
        { value: "KG", label: "kg" },
        { value: "PCS", label: "Stk" },
        { value: "BUNCH", label: "Bund" },
      ],
      getUnitLabel: (v: string) => unitLabelMap[v] ?? v,
    }),
    useSizeOptions: () => ({
      VEGETABLE_SIZE_OPTIONS: { S: "S", M: "M", L: "L" },
      sizeOptions: [
        { value: "S", label: "klein" },
        { value: "M", label: "mittel" },
        { value: "L", label: "groß" },
      ],
      getSizeLabel: (v: string) => sizeLabelMap[v] ?? v,
    }),
    useTenant: () => tenant,
  };
});

// ─── Shared test data builders ──────────────────────────────────────────────

const ARTICLE_NAMES = [
  "Karotten",
  "Kartoffeln",
  "Salat",
  "Tomaten",
  "Gurken",
  "Paprika",
  "Zwiebeln",
  "Knoblauch",
  "Spinat",
  "Mangold",
  "Radieschen",
  "Kohlrabi",
  "Blumenkohl",
  "Brokkoli",
  "Zucchini",
  "Aubergine",
  "Kürbis",
  "Rote Bete",
  "Sellerie",
  "Fenchel",
  "Lauch",
  "Petersilie",
  "Dill",
  "Basilikum",
  "Schnittlauch",
  "Koriander",
  "Rucola",
  "Feldsalat",
  "Kopfsalat",
  "Eisbergsalat",
  "Chinakohl",
  "Grünkohl",
  "Rosenkohl",
  "Wirsing",
  "Rotkohl",
  "Weißkohl",
  "Pak Choi",
  "Artischocke",
  "Spargel",
  "Erbsen",
  "Bohnen",
  "Mais",
  "Süßkartoffeln",
  "Topinambur",
  "Pastinaken",
  "Schwarzwurzel",
  "Steckrübe",
  "Rettich",
  "Meerrettich",
  "Ingwer",
  "Portulak",
  "Löwenzahn",
  "Bärlauch",
  "Kresse",
  "Radicchio",
  "Endivien",
  "Chicorée",
  "Batavia",
  "Lollo Rosso",
  "Lollo Bionda",
  "Eichblattsalat",
  "Romanesco",
  "Palmkohl",
  "Butterkohl",
  "Markstammkohl",
  "Mairübe",
  "Herbstrübe",
  "Speiserübe",
  "Stielmus",
  "Postelein",
  "Winterpostelein",
  "Barbarakraut",
  "Winterkresse",
  "Tatsoi",
  "Mizuna",
  "Senfspinat",
  "Komatsuna",
  "Asia-Salat Mix",
  "Wildkräuter Mix",
  "Microgreens",
  "Sprossen",
  "Knollensellerie",
  "Staudensellerie",
  "Bleichsellerie",
  "Schnittsellerie",
  "Liebstöckel",
  "Thymian",
  "Rosmarin",
  "Salbei",
  "Oregano",
  "Majoran",
  "Bohnenkraut",
  "Estragon",
  "Zitronenmelisse",
  "Minze",
  "Lavendel",
  "Ysop",
  "Borretsch",
  "Kapuzinerkresse",
  "Ringelblume",
];

const UNITS = ["KG", "PCS", "BUNCH"];
const SIZES = ["S", "M", "L"];

function buildLineItems(count: number): LineItemBase[] {
  return Array.from({ length: count }, (_, i) => ({
    share_article_name: ARTICLE_NAMES[i % ARTICLE_NAMES.length],
    amount: parseFloat((Math.random() * 50 + 1).toFixed(2)),
    price_per_unit: parseFloat((Math.random() * 5 + 0.5).toFixed(2)),
    unit: UNITS[i % UNITS.length],
    size: SIZES[i % SIZES.length],
    sort: i % 3 === 0 ? `Sorte ${i + 1}` : undefined,
    tax_rate: 7,
    rabatt: i % 5 === 0 ? 10 : 0,
  }));
}

function buildOfferItems(count: number) {
  return Array.from({ length: count }, (_, i) => ({
    share_article_name: ARTICLE_NAMES[i % ARTICLE_NAMES.length],
    size: SIZES[i % SIZES.length],
    sort: i % 3 === 0 ? `Sorte ${i + 1}` : undefined,
    description: i % 4 === 0 ? `Bio-Qualität` : undefined,
    amount_per_pu: parseFloat((Math.random() * 10 + 1).toFixed(2)),
    unit: UNITS[i % UNITS.length],
    price_1: parseFloat((Math.random() * 3 + 0.5).toFixed(2)),
    price_2: parseFloat((Math.random() * 2.5 + 0.4).toFixed(2)),
    price_3: parseFloat((Math.random() * 2 + 0.3).toFixed(2)),
  }));
}

// Use the realistic "seed_reseller_doc_text"-equivalent samples so the
// PDF fixtures land with the same bold / line-break / paragraph
// structure a freshly-seeded dev tenant would produce. The shared
// module is also used by the configuration preview buttons, so a
// layout regression here is caught in both places.
const tenantSettings = SAMPLE_TENANT_SETTINGS;
const footerSettings = SAMPLE_FOOTER_SETTINGS;

// ─── Invoice helpers ────────────────────────────────────────────────────────

function buildInvoiceData(itemCount: number): InvoicePDFData {
  const lineItems = buildLineItems(itemCount);
  const crateItems: LineItemBase[] = [];
  const taxBreakdown = computeTaxBreakdown(lineItems, crateItems);
  const totalNetto = taxBreakdown.reduce((s, i) => s + i.netto, 0);
  const totalTax = taxBreakdown.reduce((s, i) => s + i.tax, 0);

  return {
    invoice: {
      prefix: "RE",
      invoice_number: "2026-001",
      invoice_date: "2026-04-10",
      reseller_name: "Bio Laden GmbH",
      reseller_address: "Marktplatz 5",
      reseller_zip: "54321",
      reseller_city: "Musterstadt",
      reseller_country: "Deutschland",
      reseller_uid: "DE987654321",
      corresponding_delivery_notes: "LS-2026-001, LS-2026-002",
      is_finalized: true,
      finalized_at: "2026-04-10T12:00:00Z",
      company_name: "Test Farm GmbH",
      document_hash: "abc123def456",
    },
    lineItems,
    crateItems,
    taxBreakdown,
    totals: {
      netto: totalNetto,
      tax: totalTax,
      brutto: totalNetto + totalTax,
    },
  };
}

// ─── DeliveryNote helpers ───────────────────────────────────────────────────

function buildDeliveryNoteData(itemCount: number): DeliveryNotePDFData {
  return {
    deliveryNote: {
      prefix: "LS",
      delivery_note_number: "2026-001",
      delivery_note_date: "2026-04-10",
      reseller_name: "Bio Laden GmbH",
      reseller_address: "Marktplatz 5",
      reseller_zip: "54321",
      reseller_city: "Musterstadt",
      reseller_country: "Deutschland",
      is_finalized: true,
      finalized_at: "2026-04-10T12:00:00Z",
      document_hash: "abc123def456",
    },
    lineItems: buildLineItems(itemCount),
    crateItems: [],
  };
}

// ─── Offer helpers ──────────────────────────────────────────────────────────

function buildOfferData(itemCount: number): OfferPDFData {
  return {
    offers: buildOfferItems(itemCount),
    year: 2026,
    delivery_week: 15,
    offer_group: "1",
  };
}

// ─── Test suites ────────────────────────────────────────────────────────────

const ITEM_COUNTS = [5, 8, 10, 30, 50, 100];

// Test-generated PDF fixtures land in ``samples/pdf-test-samples/`` at the
// repo root. They're gitignored (``*.pdf`` rule) — purely for local
// inspection / perf eyeballing.
const OUTPUT_DIR = path.resolve(
  __dirname,
  "../../../../../../../samples/pdf-test-samples",
);

/** Convert a Blob to a Node.js Buffer so we can write it to disk. */
async function blobToBuffer(blob: Blob): Promise<Buffer> {
  const arrayBuffer = await blob.arrayBuffer();
  return Buffer.from(arrayBuffer);
}

describe("PDF generation – write sample files to disk", () => {
  // Create output directory once before all tests
  it("creates output directory", () => {
    fs.mkdirSync(OUTPUT_DIR, { recursive: true });
    expect(fs.existsSync(OUTPUT_DIR)).toBe(true);
  });

  describe("InvoicePDF", () => {
    it.each(ITEM_COUNTS)(
      "generates invoice with %i items",
      async (count) => {
        const data = buildInvoiceData(count);

        const blob = await pdf(
          <InvoicePDF
            data={data}
            t={t}
            qrCodeDataUrl={null}
            bankDetails={{
              iban: "DE89 1234 5678 9012 3456",
              bic: "TESTDE12",
              beneficiary: "Test Farm GmbH",
            }}
            footerSettings={footerSettings}
            lineSettings={SAMPLE_INVOICE_LINE_SETTINGS}
            tenantSettings={tenantSettings}
            previewMode
          />,
        ).toBlob();

        const filePath = path.join(OUTPUT_DIR, `invoice_${count}_items.pdf`);
        fs.writeFileSync(filePath, await blobToBuffer(blob));

        expect(blob.size).toBeGreaterThan(0);
      },
      30_000,
    );
  });

  describe("DeliveryNotePDF", () => {
    it.each(ITEM_COUNTS)(
      "generates delivery note with %i items",
      async (count) => {
        const data = buildDeliveryNoteData(count);

        const blob = await pdf(
          <DeliveryNotePDF
            data={data}
            t={t}
            footerSettings={footerSettings}
            lineSettings={SAMPLE_DELIVERY_NOTE_LINE_SETTINGS}
            tenantSettings={tenantSettings}
            previewMode
          />,
        ).toBlob();

        const filePath = path.join(
          OUTPUT_DIR,
          `delivery_note_${count}_items.pdf`,
        );
        fs.writeFileSync(filePath, await blobToBuffer(blob));

        expect(blob.size).toBeGreaterThan(0);
      },
      30_000,
    );
  });

  describe("OfferPDF", () => {
    it.each(ITEM_COUNTS)(
      "generates offer with %i items",
      async (count) => {
        const data = buildOfferData(count);

        const blob = await pdf(
          <OfferPDF
            data={data}
            t={t}
            footerSettings={footerSettings}
            lineSettings={SAMPLE_OFFER_LINE_SETTINGS}
            tenantSettings={tenantSettings}
            previewMode
          />,
        ).toBlob();

        const filePath = path.join(OUTPUT_DIR, `offer_${count}_items.pdf`);
        fs.writeFileSync(filePath, await blobToBuffer(blob));

        expect(blob.size).toBeGreaterThan(0);
      },
      30_000,
    );
  });

  // ── Currency-symbol threading ────────────────────────────────────────────
  //
  // These tests walk the JSX element tree the PDF component returns
  // (no real PDF rendering — we'd need a PDF parser otherwise) and
  // verify the per-cell currency text. Catches the regression where
  // the PDF used to hardcode ``€`` and ignored the tenant currency.
  describe("currencySymbol prop threading", () => {
    /**
     * Recursively flatten a React element tree to a single string of
     * all rendered text. Good enough for "did our currency symbol show
     * up anywhere?" assertions without a PDF parser.
     */
    function collectText(node: unknown): string {
      if (node == null || typeof node === "boolean") return "";
      if (typeof node === "string" || typeof node === "number") {
        return String(node);
      }
      if (Array.isArray(node)) {
        return node.map(collectText).join("");
      }
      if (typeof node === "object" && "props" in (node as Record<string, unknown>)) {
        const element = node as { type: unknown; props: { children?: unknown } };
        const { type, props } = element;
        // Function components → invoke once to get their tree.
        if (typeof type === "function") {
          const rendered = (type as (p: unknown) => unknown)(props);
          return collectText(rendered);
        }
        return collectText(props?.children);
      }
      return "";
    }

    it("InvoicePDF renders the passed currencySymbol on price + total cells", () => {
      const data = buildInvoiceData(5);
      const tree = (
        <InvoicePDF
          data={data}
          t={t}
          qrCodeDataUrl={null}
          bankDetails={{ iban: "DE89", bic: "BIC", beneficiary: "T" }}
          footerSettings={footerSettings}
          lineSettings={SAMPLE_INVOICE_LINE_SETTINGS}
          tenantSettings={tenantSettings}
          currencySymbol="$"
          previewMode
        />
      );
      const txt = collectText(tree);

      // Concrete cells: per-line price uses ``$``, totals use ``$``.
      expect(txt).toContain("$");
      // No leftover € from the legacy hardcode.
      expect(txt).not.toContain("€");
    });

    it("InvoicePDF defaults to € when no currencySymbol is passed", () => {
      const data = buildInvoiceData(3);
      const tree = (
        <InvoicePDF
          data={data}
          t={t}
          qrCodeDataUrl={null}
          bankDetails={{ iban: "DE89", bic: "BIC", beneficiary: "T" }}
          footerSettings={footerSettings}
          lineSettings={SAMPLE_INVOICE_LINE_SETTINGS}
          tenantSettings={tenantSettings}
          previewMode
        />
      );
      // Backwards-compatible default keeps the document rendering €.
      expect(collectText(tree)).toContain("€");
    });

    it("DeliveryNotePDF threads the passed currencySymbol into price cells", () => {
      const data = buildDeliveryNoteData(5);
      const tree = (
        <DeliveryNotePDF
          data={data}
          t={t}
          footerSettings={footerSettings}
          lineSettings={SAMPLE_DELIVERY_NOTE_LINE_SETTINGS}
          tenantSettings={tenantSettings}
          currencySymbol="CHF"
          previewMode
        />
      );
      const txt = collectText(tree);
      expect(txt).toContain("CHF");
      expect(txt).not.toContain("€");
    });
  });
});
