/**
 * Shared "realistic" tenant-side text for the reseller PDFs.
 *
 * The content matches what
 * ``apps/shared/tenants/management/commands/seed_reseller_doc_text.py``
 * writes to a freshly-provisioned dev tenant, so:
 *
 *   - The sample PDFs the frontend tests write to
 *     ``samples/pdf-fixtures/`` carry the same layout a real seeded
 *     tenant would produce — useful for eyeballing bold / line breaks
 *     / footer paragraph spacing without spinning up the backend.
 *   - The ``ConfigurationResellerDocuments`` preview buttons can
 *     optionally reuse these defaults when the tenant has nothing
 *     configured yet (currently they pull from
 *     ``useSettingsManager`` so live RTE edits already preview
 *     correctly).
 *
 * Keep this file and the Python seed in sync. If you change one,
 * change the other — there's no auto-generation step here.
 */

import type { FooterSettings, TenantPDFSettings } from "./pdfBase";

// ─── Invoice ────────────────────────────────────────────────────────────────

export const SAMPLE_INVOICE_LINE_SETTINGS = {
  entry_line_1_invoice_reseller:
    "<p>Vielen Dank für Ihre Bestellung. Anbei erhalten Sie unsere Rechnung.</p>",
  entry_line_2_invoice_reseller:
    "<p>Bitte überweisen Sie den Rechnungsbetrag unter Angabe der Rechnungsnummer.</p>",
  entry_line_3_invoice_reseller:
    "<p>Bei Rückfragen zur Rechnung wenden Sie sich gerne an unsere <strong>Buchhaltung</strong>.</p>",
  greeting_line_1_invoice_reseller:
    "<p>Mit freundlichen Grüßen aus dem Marillenhof</p>",
  greeting_line_2_invoice_reseller: "<p>Ihr Marillenhof-Team</p>",
  greeting_line_3_invoice_reseller: "<p>buchhaltung@marillenhof.example</p>",
};

// ─── Delivery note ──────────────────────────────────────────────────────────

export const SAMPLE_DELIVERY_NOTE_LINE_SETTINGS = {
  entry_line_1_delivery_note_reseller: "<p>Sehr geehrte Damen und Herren,</p>",
  entry_line_2_delivery_note_reseller:
    "<p>anbei der Lieferschein für die heutige Lieferung.</p>",
  entry_line_3_delivery_note_reseller:
    "<p>Bitte prüfen Sie die Ware bei Annahme auf <strong>Vollständigkeit</strong>.</p>",
  greeting_line_1_delivery_note_reseller: "<p>Mit freundlichen Grüßen</p>",
  greeting_line_2_delivery_note_reseller: "<p>Ihr Marillenhof-Team</p>",
  greeting_line_3_delivery_note_reseller:
    "<p>lieferung@marillenhof.example</p>",
};

// ─── Offer ──────────────────────────────────────────────────────────────────

export const SAMPLE_OFFER_LINE_SETTINGS = {
  entry_line_1_offer_reseller: "<p>Sehr geehrte Damen und Herren,</p>",
  entry_line_2_offer_reseller:
    "<p>anbei unser aktuelles Angebot für die kommende Lieferwoche.</p>",
  entry_line_3_offer_reseller:
    "<p>Alle Preise verstehen sich <em>netto</em>, zzgl. der gesetzlichen Steuer.</p>",
  // Match what ``seed_reseller_doc_text.py`` writes — including the
  // ``<a href="mailto:...">`` link, which has an unbreakable email in
  // its link text and is what surfaced the
  // "order-instructions-in-a-column" layout bug in the offer PDF.
  order_instructions_offer_reseller:
    "<p><strong>Bestellannahme:</strong> Bitte tragen Sie die gewünschte Menge in der letzten Spalte ein und senden Sie das Angebot ausgefüllt zurück an " +
    '<a href="mailto:bestellungen@marillenhof.example">bestellungen@marillenhof.example</a>.</p>' +
    "<p>Bestellschluss ist jeden Donnerstag, 12:00 Uhr. Spätere Bestellungen können nicht garantiert berücksichtigt werden.</p>",
  greeting_line_1_offer_reseller: "<p>Wir freuen uns auf Ihre Bestellung</p>",
  greeting_line_2_offer_reseller: "<p>Ihr Marillenhof-Team</p>",
  greeting_line_3_offer_reseller: "<p>bestellungen@marillenhof.example</p>",
};

// ─── Footer (shared across all three docs) ──────────────────────────────────

export const SAMPLE_FOOTER_SETTINGS: FooterSettings = {
  left_column_footer_documents_reseller:
    "<p><strong>Marillenhof CSA</strong><br/>" +
    "Hauptstraße 42<br/>" +
    "3500 Krems an der Donau<br/>" +
    "Österreich</p>" +
    "<p>+43 1 234 5678<br/>" +
    "office@marillenhof.example</p>",
  middle_column_footer_documents_reseller:
    "<p><strong>Bankverbindung</strong><br/>" +
    "Raiffeisen Krems<br/>" +
    "IBAN: AT12 3456 7890 1234 5678<br/>" +
    "BIC: RZOOAT2L</p>" +
    "<p>UID: ATU12345678</p>",
  right_column_footer_documents_reseller:
    "<p><strong>Geschäftsführung</strong><br/>" +
    "Maria Marillenbauer<br/>" +
    "Firmenbuchnummer: FN 123456 a<br/>" +
    "Firmenbuchgericht: LG Krems</p>" +
    "<p>Bio-Kontrollnummer: AT-BIO-301</p>",
};

// ─── Tenant header (name / address / contact / VAT id) ─────────────────────

export const SAMPLE_TENANT_SETTINGS: TenantPDFSettings = {
  logo: null,
  name: "Marillenhof CSA",
  address: "Hauptstraße 42",
  zip_code: "3500",
  city: "Krems an der Donau",
  country: "AT",
  email: "office@marillenhof.example",
  email_for_orders: "bestellungen@marillenhof.example",
  phone_number: "+43 1 234 5678",
  uid: "ATU12345678",
  payment_terms_reseller_in_days: 14,
};
