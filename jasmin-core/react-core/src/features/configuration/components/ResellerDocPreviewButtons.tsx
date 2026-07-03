import { DownloadOutlined } from "@ant-design/icons";
import { PDFDownloadLink } from "@react-pdf/renderer";
import { Button, Card, Flex, Typography } from "antd";
import { useEffect, useMemo, useState, type ReactElement } from "react";
import { useTranslation } from "react-i18next";

import { useCurrency, useDateFormat, useTenant } from "@hooks/index";
import DeliveryNotePDF, {
  type DeliveryNotePDFData,
} from "@features/commissioning/pdfs/forResellers/DeliveryNotePDF";
import InvoicePDF, {
  type InvoicePDFData,
} from "@features/commissioning/pdfs/forResellers/InvoicePDF";
import OfferPDF, {
  type OfferPDFData,
} from "@features/commissioning/pdfs/forResellers/OfferPDF";
import {
  buildTenantSettings,
  convertLogoToBase64,
  type FooterSettings,
  type LineItemBase,
  type ResellerInfo,
  type TaxBreakdownItem,
  type Totals,
} from "@features/commissioning/pdfs/forResellers/pdfBase";
import { buildResellerLineSettings } from "@features/commissioning/pdfs/forResellers/resellerPdfContext";

const { Text } = Typography;

interface ResellerDocPreviewButtonsProps {
  /**
   * Read the user's *live* (unsaved) edits to the reseller-doc text
   * settings. Backed by ``useSettingsManager``'s in-memory state via
   * ``SettingsPage``'s ``extraBefore`` render-prop, so the preview
   * reflects exactly what's in the form right now — saved or not.
   */
  getSettingValue: (key: string, defaultValue?: unknown) => unknown;
}

/**
 * Three "preview as PDF" buttons rendered at the top of
 * ``ConfigurationResellerDocuments``. Each generates a sample
 * delivery-note / invoice / offer PDF wired up with the user's CURRENT
 * editable text (entry lines, greeting lines, footer columns, order
 * instructions). The sample reseller and the line items are hard-coded
 * so the page works even on a brand-new tenant with no real orders.
 *
 * Implementation notes:
 *
 *   - The PDFs are rendered via ``<PDFDownloadLink>``, so the user
 *     downloads a real PDF and opens it in their viewer of choice.
 *     Avoids embedding a PDF viewer in the page.
 *   - ``tenantSettings`` is built via the existing ``buildTenantSettings``
 *     helper. Both the main ``logo`` AND the ``bio_logo`` are loaded
 *     async via the same ``convertLogoToBase64`` path that every prod
 *     generator uses, so what the preview shows is exactly what gets
 *     persisted to real invoices/delivery notes/offers later. When a
 *     logo isn't uploaded yet the corresponding image just renders
 *     nothing (or the ``LOGO`` placeholder box for the main logo when
 *     ``previewMode`` is on) — the rest of the layout is unaffected.
 *   - All editable text fields read from ``getSettingValue``, so the
 *     download mirrors unsaved RTE edits. Tenant scalars (currency,
 *     ``number_locale``, ``payment_terms_reseller_in_days`` …) read
 *     from the cached ``getSetting`` in ``TenantContext`` since they
 *     aren't editable on this page.
 */
export default function ResellerDocPreviewButtons({
  getSettingValue,
}: ResellerDocPreviewButtonsProps) {
  const { t } = useTranslation();
  const { tenant, getSetting, logoUrl, bioLogoUrl } = useTenant();
  const { currencySymbol } = useCurrency();
  const { dateFormat } = useDateFormat();
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

  // ---- Shared sample data ----
  const sampleReseller: ResellerInfo = useMemo(
    () => ({
      reseller_name: "Bio Markt Wien (Beispiel)",
      reseller_address: "Marktplatz 1",
      reseller_zip: "1010",
      reseller_city: "Wien",
      reseller_country: "AT",
      reseller_uid: "ATU87654321",
      company_name: "Bio Markt GmbH",
    }),
    [],
  );

  // One organic + one in-conversion + one conventional row, so the
  // preview exercises every branch of the EU 2018/848 disclosure (the
  // `*` mark, the `**` mark, and the unmarked row) AND both footer
  // lines simultaneously. The whole block self-suppresses when the
  // tenant has no ``organic_control_number``, so non-certified tenants
  // see no marks even though the mock data carries them.
  const sampleLineItems: LineItemBase[] = useMemo(
    () => [
      {
        share_article_name: "Testgemüse 1",
        sort: "Sorte 1",
        amount: 5,
        price_per_unit: 4.5,
        unit: "KG",
        size: "M",
        tax_rate: 10,
        rabatt: 0,
        line_netto: 22.5,
        organic_status: "organic",
      },
      {
        share_article_name: "Testgemüse 2",
        sort: "Sorte 2",
        amount: 8,
        price_per_unit: 3.2,
        unit: "KG",
        size: "M",
        tax_rate: 10,
        rabatt: 0,
        line_netto: 25.6,
        organic_status: "in_conversion",
      },
      {
        share_article_name: "Testgemüse 3",
        sort: "Sorte 3",
        amount: 12,
        price_per_unit: 1.5,
        unit: "Stk",
        size: "M",
        tax_rate: 10,
        rabatt: 0,
        line_netto: 18.0,
        organic_status: "conventional",
      },
    ],
    [],
  );

  const sampleCrateItems: LineItemBase[] = useMemo(() => [], []);
  const sampleTaxBreakdown: TaxBreakdownItem[] = useMemo(
    () => [{ rate: 10, netto: 66.1, tax: 6.61, brutto: 72.71 }],
    [],
  );
  const sampleTotals: Totals = useMemo(
    () => ({ netto: 66.1, tax: 6.61, brutto: 72.71 }),
    [],
  );

  // ---- Tenant + footer overlay ----
  const tenantSettings = useMemo(
    () =>
      buildTenantSettings(
        tenant as Record<string, unknown>,
        logoDataUrl,
        getSetting,
        bioLogoDataUrl,
      ),
    [tenant, getSetting, logoDataUrl, bioLogoDataUrl],
  );

  const footerSettings: FooterSettings = useMemo(
    () => ({
      left_column_footer_documents_reseller: getSettingValue(
        "left_column_footer_documents_reseller",
      ) as string | undefined,
      middle_column_footer_documents_reseller: getSettingValue(
        "middle_column_footer_documents_reseller",
      ) as string | undefined,
      right_column_footer_documents_reseller: getSettingValue(
        "right_column_footer_documents_reseller",
      ) as string | undefined,
    }),
    [getSettingValue],
  );

  // ---- Per-doc samples + line settings ----
  const deliveryNoteDoc: ReactElement = useMemo(() => {
    const data: DeliveryNotePDFData = {
      deliveryNote: {
        prefix: "LS",
        delivery_note_number: 42,
        delivery_note_date: new Date().toISOString().slice(0, 10),
        ...sampleReseller,
        is_finalized: false,
      },
      lineItems: sampleLineItems,
      crateItems: sampleCrateItems,
    };
    return (
      <DeliveryNotePDF
        data={data}
        t={t}
        tenantSettings={tenantSettings}
        footerSettings={footerSettings}
        currencySymbol={currencySymbol}
        dateFormat={dateFormat}
        previewMode
        lineSettings={buildResellerLineSettings(
          getSettingValue,
          "delivery_note",
        )}
      />
    );
  }, [
    sampleReseller,
    sampleLineItems,
    sampleCrateItems,
    tenantSettings,
    footerSettings,
    getSettingValue,
    currencySymbol,
    dateFormat,
    t,
  ]);

  const invoiceDoc: ReactElement = useMemo(() => {
    const data: InvoicePDFData = {
      invoice: {
        prefix: "RE",
        invoice_number: 1234,
        invoice_date: new Date().toISOString().slice(0, 10),
        ...sampleReseller,
        is_finalized: false,
        document_type: "invoice",
      },
      lineItems: sampleLineItems,
      crateItems: sampleCrateItems,
      taxBreakdown: sampleTaxBreakdown,
      totals: sampleTotals,
    };
    return (
      <InvoicePDF
        data={data}
        t={t}
        tenantSettings={tenantSettings}
        footerSettings={footerSettings}
        currencySymbol={currencySymbol}
        dateFormat={dateFormat}
        previewMode
        lineSettings={buildResellerLineSettings(getSettingValue, "invoice")}
      />
    );
  }, [
    sampleReseller,
    sampleLineItems,
    sampleCrateItems,
    sampleTaxBreakdown,
    sampleTotals,
    tenantSettings,
    footerSettings,
    getSettingValue,
    currencySymbol,
    dateFormat,
    t,
  ]);

  // Offer tiers + per-PU mode: both editable on this configuration
  // page, so both are read via ``getSettingValue`` to reflect unsaved
  // edits in the preview. ``used_tiers_for_offers`` falls back to
  // ``[1]`` (single-tier mode) to match the production behaviour in
  // ``OfferPDFGenerator``.
  const usedTiersForOffers = getSettingValue("used_tiers_for_offers") as
    | number[]
    | undefined;
  const finalTiers = useMemo(
    () =>
      usedTiersForOffers && usedTiersForOffers.length > 0
        ? usedTiersForOffers
        : [1],
    [usedTiersForOffers],
  );
  const tierLabels = useMemo(
    () =>
      finalTiers.map((tier) => t("commissioning.tier", { tier }) || `T${tier}`),
    [finalTiers, t],
  );
  const pricesPerPU = getSettingValue(
    "offer_prices_are_per_pu",
    false,
  ) as boolean;

  const offerDoc: ReactElement = useMemo(() => {
    const data: OfferPDFData = {
      offers: [
        // Same three-status mix as the delivery-note / invoice
        // samples so all three previews look consistent.
        {
          share_article_name: "Marillen",
          sort: "Klosterneuburger",
          description: "Erste Ernte",
          amount_per_pu: 5,
          unit: "KG",
          size: "M",
          price_1: 4.5,
          price_2: 4.2,
          price_3: 3.9,
          organic_status: "organic",
        },
        {
          share_article_name: "Tomaten",
          sort: "San Marzano",
          description: "Freilandanbau",
          amount_per_pu: 6,
          unit: "KG",
          size: "M",
          price_1: 3.2,
          price_2: 3.0,
          price_3: 2.7,
          organic_status: "in_conversion",
        },
        {
          share_article_name: "Salat",
          sort: "Eichblatt",
          description: "Glashaus",
          amount_per_pu: 1,
          unit: "Stk",
          size: "M",
          price_1: 1.5,
          price_2: 1.4,
          price_3: 1.25,
          organic_status: "conventional",
        },
      ],
      year: new Date().getFullYear(),
      delivery_week: 32,
    };
    return (
      <OfferPDF
        data={data}
        t={t}
        tenantSettings={tenantSettings}
        footerSettings={footerSettings}
        currencySymbol={currencySymbol}
        dateFormat={dateFormat}
        resellerInfo={sampleReseller}
        previewMode
        tierLabels={tierLabels}
        pricesPerPU={pricesPerPU}
        lineSettings={buildResellerLineSettings(getSettingValue, "offer")}
      />
    );
  }, [
    sampleReseller,
    tenantSettings,
    footerSettings,
    getSettingValue,
    tierLabels,
    pricesPerPU,
    currencySymbol,
    dateFormat,
    t,
  ]);

  return (
    <Card
      title={t("settings.reseller.preview.title")}
      style={{ width: "100%", maxWidth: 900 }}
      styles={{ body: { padding: "16px" } }}
      className="settings-card-header"
    >
      <Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
        {t("settings.reseller.preview.description")}
      </Text>
      <Flex gap="middle" wrap="wrap">
        <PDFDownloadLink document={offerDoc} fileName="preview-offer.pdf">
          <Button icon={<DownloadOutlined />}>
            {t("settings.reseller.preview.offer")}
          </Button>
        </PDFDownloadLink>
        <PDFDownloadLink
          document={deliveryNoteDoc}
          fileName="preview-delivery-note.pdf"
        >
          <Button icon={<DownloadOutlined />}>
            {t("settings.reseller.preview.delivery_note")}
          </Button>
        </PDFDownloadLink>
        <PDFDownloadLink document={invoiceDoc} fileName="preview-invoice.pdf">
          <Button icon={<DownloadOutlined />}>
            {t("settings.reseller.preview.invoice")}
          </Button>
        </PDFDownloadLink>

      </Flex>
    </Card>
  );
}
