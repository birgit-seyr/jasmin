import {
  Document,
  Image,
  Page,
  StyleSheet,
  Text,
  View,
} from "@react-pdf/renderer";
import dayjs from "dayjs";
import type { TFunction } from "i18next";
import { getVegetableSizeLabelPure } from "@hooks/useVegetableSizeOptions";
import { getUnitLabelPure } from "@hooks/useUnitOptions";
import { formatCurrency } from "@shared/utils/currency";
import { formatNumber } from "@shared/utils/numberFormat";
import { itemLineNetto } from "@shared/utils/lineNetto";
import PDFRichText from "./PDFRichText";
import {
  baseStyles,
  formatAmount,
  type FooterSettings,
  isCreditNote,
  type LineItemBase,
  organicMarker,
  type TaxBreakdownItem,
  type TenantPDFSettings,
  type Totals,
} from "./pdfBase";
import {
  PDFEntryLines,
  PDFFooter,
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
      marginTop: 5,
      marginBottom: 10,
    },
    subtitle: {
      fontSize: 12,
      color: "#666",
      marginBottom: 20,
    },
    taxSection: {
      marginTop: 3,
      paddingTop: 3,
      borderTopWidth: 2,
      borderTopColor: "#000",
    },
    taxBreakdownRow: {
      flexDirection: "row",
      justifyContent: "flex-end",
      marginBottom: 2,
      fontSize: 9,
    },
    taxBreakdownLabel: {
      width: 75,
      textAlign: "right",
      marginRight: 8,
    },
    taxBreakdownValue: {
      width: 60,
      textAlign: "right",
    },
    taxSummaryRow: {
      flexDirection: "row",
      justifyContent: "flex-end",
      marginBottom: 0,
    },
    taxSummaryLabel: {
      width: 130,
      textAlign: "right",
      marginRight: 15,
    },
    taxSummaryValue: {
      width: 80,
      textAlign: "right",
      fontWeight: "bold",
    },
    bottomSection: {
      flexDirection: "row",
      marginTop: 8,
    },
    taxColumn: {
      width: "50%",
    },
    qrColumn: {
      width: "50%",
      paddingLeft: 15,
      borderLeftWidth: 1,
      borderLeftColor: "#ddd",
    },
    qrCodeContainer: {
      flexDirection: "row",
      alignItems: "flex-start",
    },
    qrCodeImage: {
      width: 55,
      height: 55,
      marginRight: 10,
    },
    qrCodeText: {
      flex: 1,
      fontSize: 8,
      lineHeight: 1.4,
    },
  }),
};

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
  corresponding_delivery_notes?: string;
  is_finalized?: boolean;
  finalized_at?: string | null;
  document_hash?: string;
  company_name?: string;
  document_type?: string;
  cancels_invoice_number?: string | null;
  correction_reason?: string | null;
}

interface BankDetails {
  iban?: string;
  bic?: string;
  beneficiary?: string;
}

interface LineSettings {
  entry_line_1_invoice_reseller?: string;
  entry_line_2_invoice_reseller?: string;
  entry_line_3_invoice_reseller?: string;
  greeting_line_1_invoice_reseller?: string;
  greeting_line_2_invoice_reseller?: string;
  greeting_line_3_invoice_reseller?: string;
}

export interface InvoicePDFData {
  invoice: InvoiceData;
  lineItems: LineItemBase[];
  crateItems: LineItemBase[];
  taxBreakdown: TaxBreakdownItem[];
  totals: Totals;
}

/**
 * Per-invoice payment terms resolved by the caller (typically via
 * ``Reseller.get_payment_terms_days()`` and the matching Skonto helper
 * on the backend). When the prop is omitted, the PDF falls back to the
 * tenant defaults on ``tenantSettings`` so old callers keep working.
 */
export interface InvoicePaymentTerms {
  days: number;
  earlyPaymentDiscountPercent?: number | null;
  earlyPaymentDiscountDays?: number | null;
}

interface InvoicePDFProps {
  data: InvoicePDFData;
  t: TFunction;
  qrCodeDataUrl?: string | null;
  bankDetails?: BankDetails;
  footerSettings?: FooterSettings;
  lineSettings?: LineSettings;
  tenantSettings: TenantPDFSettings;
  /**
   * Symbol appended after every price/total cell (e.g. ``"€"``,
   * ``"$"``, ``"CHF"``). The PDF used to hardcode ``"€"``; callers now
   * thread ``useCurrency().currencySymbol`` so the rendered document
   * matches the tenant's configured currency. Default ``"€"`` keeps
   * any non-migrated caller rendering as before.
   */
  currencySymbol?: string;
  /**
   * Display date format threaded from the caller's ``useDateFormat()``;
   * default keeps legacy ``DD.MM.YYYY``.
   */
  dateFormat?: string;
  /** Per-invoice resolved payment terms (Reseller override → Tenant default). */
  paymentTerms?: InvoicePaymentTerms;
  /**
   * Preview mode: when no logo or QR code is supplied, render bordered
   * ``LOGO`` / ``QR`` placeholders so the layout is visible to the
   * tenant in the configuration preview buttons.
   */
  previewMode?: boolean;
}

export default function InvoicePDF({
  data,
  t,
  qrCodeDataUrl,
  bankDetails,
  footerSettings,
  lineSettings,
  tenantSettings,
  currencySymbol = "€",
  dateFormat = "DD.MM.YYYY",
  paymentTerms,
  previewMode = false,
}: InvoicePDFProps) {
  // Resolve payment terms: per-invoice prop > tenant default > 14.
  // Same shape ZUGFeRD uses, kept here so the visible PDF and the
  // embedded XML always print the same terms.
  const resolvedTerms: InvoicePaymentTerms = paymentTerms ?? {
    days: tenantSettings.payment_terms_reseller_in_days || 14,
    earlyPaymentDiscountPercent:
      tenantSettings.early_payment_discount_percent ?? null,
    earlyPaymentDiscountDays:
      tenantSettings.early_payment_discount_days ?? null,
  };
  const skontoActive =
    resolvedTerms.earlyPaymentDiscountPercent != null &&
    resolvedTerms.earlyPaymentDiscountDays != null &&
    Number(resolvedTerms.earlyPaymentDiscountPercent) > 0;
  const { invoice, lineItems, crateItems, taxBreakdown, totals } = data;
  const locale = tenantSettings?.number_locale ?? "de-DE";
  const getUnitLabel = (value: string) => getUnitLabelPure(value, t);
  const getVegetableSizeLabel = (value: string) => getVegetableSizeLabelPure(value, t);

  const creditNote = isCreditNote(invoice.document_type);
  const documentTitle = creditNote
    ? t("commissioning.storno_invoice_title")
    : t("commissioning.invoice");

  return (
    <Document>
      <Page size="A4" style={styles.page}>
        <PDFLogo tenantSettings={tenantSettings} placeholder={previewMode} />
        <PDFResellerInfo
          tenantSettings={tenantSettings}
          resellerInfo={invoice}
        />

        <PDFTenantInfo tenantSettings={tenantSettings}>
          <Text style={[styles.label, { marginTop: 6 }]}>
            {t("commissioning.invoice_number_pdf")}
            {invoice.prefix}-{invoice.invoice_number}
          </Text>
          <Text style={styles.label}>
            {t("commissioning.invoice_date")}
            {dayjs(invoice.invoice_date).format(dateFormat)}
          </Text>
          {creditNote && invoice.cancels_invoice_number && (
            <Text style={styles.label}>
              {t("commissioning.storno_reference")}
              {invoice.cancels_invoice_number}
            </Text>
          )}
          {!creditNote && (
            <Text style={styles.label}>
              {t("commissioning.corresponding_delivery_notes")}
              {invoice.corresponding_delivery_notes}
            </Text>
          )}
          {creditNote && invoice.correction_reason && (
            <Text style={styles.label}>
              {t("commissioning.correction_reason")}:{" "}
              {invoice.correction_reason}
            </Text>
          )}
        </PDFTenantInfo>

        <View style={styles.header}>
          <Text style={styles.title}>{documentTitle}</Text>
        </View>

        {lineSettings && (
          <View style={styles.entryBlock}>
            <PDFEntryLines
              lines={[
                lineSettings.entry_line_1_invoice_reseller,
                lineSettings.entry_line_2_invoice_reseller,
                lineSettings.entry_line_3_invoice_reseller,
              ]}
            />
          </View>
        )}

        {/* Line Items Table */}
        <View style={styles.table}>
          <View style={styles.tableHeader} fixed>
            <Text style={styles.col1}>
              {t("commissioning.share_article_name")}
            </Text>
            <Text style={styles.col2}>{t("commissioning.amount")}</Text>
            <Text style={styles.col3}>{t("commissioning.unit")}</Text>
            <Text style={styles.col4}>
              {t("commissioning.price_per_unit_invoice_pdf")}
            </Text>
            <Text style={styles.col5}>{t("commissioning.rabatt_pdf")}</Text>
            <Text style={styles.col7}>{t("commissioning.line_netto")}</Text>
            <Text style={styles.col6}>{t("commissioning.ust")}</Text>
          </View>

          {lineItems.map((item, index) => {
            // Authoritative cent-rounded net from the backend
            // (models/mixin.py line_netto), not a client float recompute, so
            // the printed line totals sum to the printed document total. The
            // shared helper prefers the backend value and rounds the
            // recompute fallback the same way the backend does.
            const finalPrice = itemLineNetto(item);

            return (
              <View key={index} style={styles.tableRow} wrap={false}>
                <View style={styles.col1}>
                  <Text>
                    {item.share_article_name}
                    {item.size && item.size !== "M"
                      ? `, ${getVegetableSizeLabel(item.size)}`
                      : ""}
                    {tenantSettings.organic_control_number
                      ? organicMarker(item.organic_status)
                      : ""}
                  </Text>
                  {item.sort ? (
                    <Text style={[styles.text_muted, { fontSize: 7 }]}>
                      {item.sort}
                    </Text>
                  ) : null}
                </View>
                <Text style={styles.col2}>
                  {formatAmount(item.amount, item.unit, locale)}
                </Text>
                <Text style={styles.col3}>{getUnitLabel(item.unit ?? "")}</Text>
                <Text style={styles.col4}>
                  {item.price_per_unit
                    ? `${formatCurrency(formatNumber(item.price_per_unit, 2, locale), currencySymbol)}/${getUnitLabel(item.unit ?? "")}`
                    : "-"}
                </Text>
                <Text style={styles.col5}>
                  {item.rabatt ? `${item.rabatt} %` : "-"}
                </Text>
                <Text style={styles.col7}>
                  {formatCurrency(formatNumber(finalPrice, 2, locale), currencySymbol)}
                </Text>
                <Text style={styles.col6}>
                  {formatNumber(item.tax_rate || 0, 2, locale)} %
                </Text>
              </View>
            );
          })}

          {crateItems.map((item, index) => {
            // Authoritative cent-rounded net from the backend
            // (models/mixin.py line_netto), not a client float recompute, so
            // the printed line totals sum to the printed document total. The
            // shared helper prefers the backend value and rounds the
            // recompute fallback the same way the backend does.
            const finalPrice = itemLineNetto(item);

            return (
              <View key={index} style={styles.tableRow} wrap={false}>
                <Text style={styles.col1}>{item.crate_type_name}</Text>
                <Text style={styles.col2}>
                  {formatNumber(item.amount, 0, locale)}
                </Text>
                <Text style={styles.col3}>
                  {t("commissioning.piece_short")}
                </Text>
                <Text style={styles.col4}>
                  {item.price_per_unit
                    ? `${formatCurrency(formatNumber(item.price_per_unit, 2, locale), currencySymbol)}/${t("commissioning.piece_short")}`
                    : "-"}
                </Text>
                <Text style={styles.col5}>
                  {item.rabatt ? `${item.rabatt}%` : "-"}
                </Text>
                <Text style={styles.col7}>
                  {formatCurrency(formatNumber(finalPrice, 2, locale), currencySymbol)}
                </Text>
                <Text style={styles.col6}>
                  {formatNumber(item.tax_rate || 0, 2, locale)} %
                </Text>
              </View>
            );
          })}
        </View>

        {/* Tax Breakdown */}
        <View style={styles.taxSection} wrap={false}>
          {taxBreakdown.map((item, index) => (
            <View key={index} style={styles.taxBreakdownRow}>
              <Text style={styles.taxBreakdownLabel}>
                {t("commissioning.netto")} ({item.rate}%):
              </Text>
              <Text style={styles.taxBreakdownValue}>
                {formatCurrency(formatNumber(item.netto, 2, locale), currencySymbol)}
              </Text>
              <Text style={[styles.taxBreakdownLabel, { marginLeft: 10 }]}>
                {t("commissioning.ust")} ({item.rate}%):
              </Text>
              <Text style={styles.taxBreakdownValue}>
                {formatCurrency(formatNumber(item.tax, 2, locale), currencySymbol)}
              </Text>
            </View>
          ))}

          <View
            style={{
              borderTopWidth: 1,
              borderTopColor: "#ddd",
              marginTop: 3,
              marginBottom: 3,
            }}
          />

          <View style={styles.taxSummaryRow}>
            <Text style={styles.taxSummaryLabel}>
              {t("commissioning.total_sum_netto_invoice_details")}:
            </Text>
            <Text style={styles.taxSummaryValue}>
              {formatCurrency(formatNumber(totals.netto, 2, locale), currencySymbol)}
            </Text>
          </View>

          <View style={styles.taxSummaryRow}>
            <Text style={styles.taxSummaryLabel}>
              {t("commissioning.total_sum_ust_invoice_details")}:
            </Text>
            <Text style={styles.taxSummaryValue}>
              {formatCurrency(formatNumber(totals.tax, 2, locale), currencySymbol)}
            </Text>
          </View>

          <View
            style={[
              styles.taxSummaryRow,
              {
                marginTop: 3,
                paddingTop: 5,
                borderTopWidth: 2,
                borderTopColor: "#000",
              },
            ]}
          >
            <Text
              style={[
                styles.taxSummaryLabel,
                { fontSize: 12, fontWeight: "bold" },
              ]}
            >
              {t("commissioning.total_sum_brutto_invoice_details")}:
            </Text>
            <Text style={[styles.taxSummaryValue, { fontSize: 12 }]}>
              {formatCurrency(formatNumber(totals.brutto, 2, locale), currencySymbol)}
            </Text>
          </View>
        </View>

        {/* EU 2018/848 organic disclosure. Placed just above the QR
            section so it stays with the legally-relevant footer block
            and survives page breaks alongside the payment info. */}
        <PDFOrganicFooter
          tenantSettings={tenantSettings}
          lineItems={lineItems}
          t={t}
        />

        {/* QR Code (left) + Greeting/Payment terms (right) — 50/50 */}
        {!creditNote && (
          <View style={styles.bottomSection} wrap={false}>
            {qrCodeDataUrl && bankDetails ? (
              <View style={styles.taxColumn}>
                <View style={styles.qrCodeContainer}>
                  <Image
                    src={qrCodeDataUrl}
                    style={styles.qrCodeImage}
                    cache={false}
                  />
                  <View style={styles.qrCodeText}>
                    <Text style={{ fontWeight: "bold", marginBottom: 2 }}>
                      {t("commissioning.payment_information")}
                    </Text>
                    <Text>{t("commissioning.scan_qr_payment")}</Text>
                    <Text>IBAN: {bankDetails.iban || "N/A"}</Text>
                    <Text>
                      {formatCurrency(formatNumber(totals.brutto, 2, locale), currencySymbol)}
                    </Text>
                    <Text>
                      {invoice.prefix}-{invoice.invoice_number}
                    </Text>
                  </View>
                </View>
              </View>
            ) : previewMode ? (
              <View style={styles.taxColumn}>
                <View style={styles.qrCodeContainer}>
                  <View
                    style={[
                      styles.qrCodeImage,
                      {
                        borderWidth: 1,
                        borderColor: "#999",
                        borderStyle: "dashed",
                        alignItems: "center",
                        justifyContent: "center",
                      },
                    ]}
                  >
                    <Text style={[styles.text_muted, { fontSize: 8 }]}>QR</Text>
                  </View>
                  <View style={styles.qrCodeText}>
                    <Text style={{ fontWeight: "bold", marginBottom: 2 }}>
                      {t("commissioning.payment_information")}
                    </Text>
                    <Text>{t("commissioning.scan_qr_payment")}</Text>
                  </View>
                </View>
              </View>
            ) : null}

            <View style={styles.qrColumn}>
              <View style={styles.greetingSection}>
                <PDFRichText
                  html={lineSettings?.greeting_line_1_invoice_reseller}
                />
                <PDFRichText
                  html={lineSettings?.greeting_line_2_invoice_reseller}
                />
                <PDFRichText
                  html={lineSettings?.greeting_line_3_invoice_reseller}
                />
                <Text>
                  {t("commissioning.payment_terms_invoice_pdf", {
                    days: resolvedTerms.days || 14,
                  })}
                </Text>
                {skontoActive && (
                  <Text>
                    {t("commissioning.early_payment_discount_invoice_pdf", {
                      percent: resolvedTerms.earlyPaymentDiscountPercent,
                      days: resolvedTerms.earlyPaymentDiscountDays,
                    })}
                  </Text>
                )}
              </View>
            </View>
          </View>
        )}

        {invoice.is_finalized && (
          <PDFHashBar
            documentHash={invoice.document_hash}
            finalizedAt={invoice.finalized_at}
            dateFormat={dateFormat}
            t={t}
          />
        )}

        <PDFFooter footerSettings={footerSettings} />
      </Page>
    </Document>
  );
}
