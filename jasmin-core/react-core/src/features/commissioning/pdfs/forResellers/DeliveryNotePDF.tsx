import { Document, Page, StyleSheet, Text, View } from "@react-pdf/renderer";
import dayjs from "dayjs";
import type { TFunction } from "i18next";
import { getVegetableSizeLabelPure } from "@hooks/useVegetableSizeOptions";
import { getUnitLabelPure } from "@hooks/useUnitOptions";
import { formatCurrency } from "@shared/utils/currency";
import { formatNumber } from "@shared/utils/numberFormat";
import {
  baseStyles,
  formatAmount,
  type FooterSettings,
  type LineItemBase,
  organicMarker,
  type TenantPDFSettings,
} from "./pdfBase";
import {
  PDFEntryLines,
  PDFFooter,
  PDFGreetingLines,
  PDFHashBar,
  PDFLogo,
  PDFOrganicFooter,
  PDFResellerInfo,
  PDFTenantInfo,
} from "./PDFSharedComponents";

const styles = {
  ...baseStyles,
  ...StyleSheet.create({
    // Spacer to push the entry lines below the absolutely-positioned
    // title (``baseStyles.header`` is at top: 200). See OfferPDF for
    // the longer rationale.
    entryBlock: {
      width: "100%",
      marginTop: 40,
    },
    articleColumn: { width: "24%" },
    sortColumn: { width: "21%", paddingLeft: 5 },
    amountColumn: { width: "10%", textAlign: "right", paddingRight: 5 },
    unitColumn: { width: "10%", textAlign: "left", paddingLeft: 5 },
    sizeColumn: { width: "10%", textAlign: "center", paddingRight: 5 },
    priceColumn: { width: "25%", textAlign: "right", paddingRight: 5 },
  }),
};

interface DeliveryNoteData {
  prefix?: string;
  delivery_note_number?: string | number;
  delivery_note_date?: string;
  reseller_name?: string | null;
  reseller_address?: string | null;
  reseller_zip?: string | null;
  reseller_city?: string | null;
  reseller_country?: string | null;
  reseller_uid?: string | null;
  is_finalized?: boolean;
  finalized_at?: string | null;
  document_hash?: string;
}

interface LineSettings {
  entry_line_1_delivery_note_reseller?: string;
  entry_line_2_delivery_note_reseller?: string;
  entry_line_3_delivery_note_reseller?: string;
  greeting_line_1_delivery_note_reseller?: string;
  greeting_line_2_delivery_note_reseller?: string;
  greeting_line_3_delivery_note_reseller?: string;
}

export interface DeliveryNotePDFData {
  deliveryNote: DeliveryNoteData;
  lineItems: LineItemBase[];
  crateItems: LineItemBase[];
}

interface DeliveryNotePDFProps {
  data: DeliveryNotePDFData;
  t: TFunction;
  footerSettings?: FooterSettings;
  lineSettings?: LineSettings;
  tenantSettings: TenantPDFSettings;
  /**
   * Symbol appended after every price cell (e.g. ``"€"``, ``"$"``,
   * ``"CHF"``). Callers thread ``useCurrency().currencySymbol`` so the
   * rendered document matches the tenant's configured currency.
   */
  currencySymbol?: string;
  /**
   * Display date format threaded from the caller's ``useDateFormat()``;
   * defaults to ``DD.MM.YYYY``.
   */
  dateFormat?: string;
  /** Render the bordered ``LOGO`` placeholder when the tenant has no
   * logo set. Used by the configuration preview buttons. */
  previewMode?: boolean;
}

export default function DeliveryNotePDF({
  data,
  t,
  footerSettings,
  lineSettings,
  tenantSettings,
  currencySymbol = "€",
  dateFormat = "DD.MM.YYYY",
  previewMode = false,
}: DeliveryNotePDFProps) {
  const { deliveryNote, lineItems, crateItems } = data;
  const locale = tenantSettings?.number_locale ?? "de-DE";
  const getUnitLabel = (value: string) => getUnitLabelPure(value, t);
  const getVegetableSizeLabel = (value: string) => getVegetableSizeLabelPure(value, t);

  return (
    <Document>
      <Page size="A4" style={styles.page}>
        <PDFLogo tenantSettings={tenantSettings} placeholder={previewMode} />
        <PDFResellerInfo
          tenantSettings={tenantSettings}
          resellerInfo={deliveryNote}
        />

        <View style={styles.header}>
          <Text style={styles.title}>{t("commissioning.delivery_note")}</Text>
        </View>

        <PDFTenantInfo tenantSettings={tenantSettings}>
          <Text style={[styles.label, { marginTop: 6 }]}>
            {t("commissioning.delivery_note_number")}
            {deliveryNote.prefix}-{deliveryNote.delivery_note_number}
          </Text>
          <Text style={styles.label}>
            {t("commissioning.delivery_note_date")}
            {dayjs(deliveryNote.delivery_note_date).format(dateFormat)}
          </Text>
        </PDFTenantInfo>

        {lineSettings && (
          <View style={styles.entryBlock}>
            <PDFEntryLines
              lines={[
                lineSettings.entry_line_1_delivery_note_reseller,
                lineSettings.entry_line_2_delivery_note_reseller,
                lineSettings.entry_line_3_delivery_note_reseller,
              ]}
            />
          </View>
        )}

        {/* Line Items Table */}
        <View style={styles.table}>
          <View style={styles.tableHeader} fixed>
            <Text style={styles.articleColumn}>
              {t("commissioning.share_article_name")}
            </Text>
            <Text style={styles.sortColumn}>{t("commissioning.sort")}</Text>
            <Text style={styles.sizeColumn}>{t("commissioning.size")}</Text>
            <Text style={styles.amountColumn}>{t("commissioning.amount")}</Text>
            <Text style={styles.unitColumn}>{t("commissioning.unit")}</Text>
            <Text style={styles.priceColumn}>
              {t("commissioning.price_per_unit_invoice_pdf")}
            </Text>
          </View>

          {lineItems.map((item, index) => (
            <View key={index} style={styles.tableRow} wrap={false}>
              <Text style={styles.articleColumn}>
                {item.share_article_name}
                {tenantSettings.organic_control_number
                  ? organicMarker(item.organic_status)
                  : ""}
              </Text>
              <Text style={styles.sortColumn}>{item.sort || "-"}</Text>
              <Text style={styles.sizeColumn}>
                {item.size && item.size !== "M"
                  ? getVegetableSizeLabel(item.size)
                  : "-"}
              </Text>
              <Text style={styles.amountColumn}>
                {formatAmount(item.amount, item.unit, locale)}
              </Text>
              <Text style={styles.unitColumn}>{getUnitLabel(item.unit ?? "")}</Text>
              <Text style={styles.priceColumn}>
                {item.price_per_unit
                  ? `${formatCurrency(formatNumber(item.price_per_unit, 2, locale), currencySymbol)}/${getUnitLabel(item.unit ?? "")}`
                  : "-"}
              </Text>
            </View>
          ))}

          {/* Presence-based: render crate rows whenever the document HAS them.
              The setting gates crate CREATION (backend), so an off-tenant's
              documents carry no crate_items and nothing renders — while a doc
              that already has crates still reconciles to its (crate-inclusive)
              total, incl. finalized/immutable ones. */}
          {crateItems.map((item, index) => (
            <View key={index} style={styles.tableRow} wrap={false}>
              <Text style={styles.articleColumn}>{item.crate_type_name}</Text>
              <Text style={styles.sortColumn}>-</Text>
              <Text style={styles.sizeColumn}>-</Text>
              <Text style={styles.amountColumn}>
                {formatNumber(item.amount, 0, locale)}
              </Text>
              {/* Crates are always counted in pieces — matches the "/piece"
                  price denominator below. ``item.unit`` is empty for crates. */}
              <Text style={styles.unitColumn}>{t("commissioning.piece_short")}</Text>
              <Text style={styles.priceColumn}>
                {item.price_per_unit ? `${formatCurrency(formatNumber(item.price_per_unit, 2, locale), currencySymbol)}/${t("commissioning.piece_short")}` : "-"}
              </Text>
            </View>
          ))}
        </View>

        <PDFOrganicFooter
          tenantSettings={tenantSettings}
          lineItems={lineItems}
          t={t}
        />

        {lineSettings && (
          <PDFGreetingLines
            lines={[
              lineSettings.greeting_line_1_delivery_note_reseller,
              lineSettings.greeting_line_2_delivery_note_reseller,
              lineSettings.greeting_line_3_delivery_note_reseller,
            ]}
          />
        )}

        {deliveryNote.is_finalized && (
          <PDFHashBar
            documentHash={deliveryNote.document_hash}
            finalizedAt={deliveryNote.finalized_at}
            dateFormat={dateFormat}
            t={t}
          />
        )}

        <PDFFooter footerSettings={footerSettings} />
      </Page>
    </Document>
  );
}
