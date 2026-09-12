import { Document, Page, StyleSheet, Text, View } from "@react-pdf/renderer";
import dayjs from "dayjs";
import type { TFunction } from "i18next";
import { useVegetableSizeOptions, useUnitOptions } from "@hooks/index";
import { formatNumber } from "@shared/utils/numberFormat";
import {
  baseStyles,
  type FooterSettings,
  type LineItemBase,
  organicMarker,
  type OrganicStatus,
  type ResellerInfo,
  type TenantPDFSettings,
} from "./pdfBase";
import {
  PDFEntryLines,
  PDFFooter,
  PDFGreetingLines,
  PDFLogo,
  PDFOrganicFooter,
  PDFResellerInfo,
  PDFTenantInfo,
} from "./PDFSharedComponents";

// OfferPDF reuses the shared ``baseStyles.table`` /
// ``baseStyles.tableHeader`` / ``baseStyles.tableRow`` (the same ones
// the delivery note and invoice use) so all three reseller documents
// have a visually consistent table. Only the column widths are
// document-specific (different column set).
const cellBase = {
  paddingHorizontal: 3,
  paddingVertical: 2,
};

const styles = {
  ...baseStyles,
  ...StyleSheet.create({
    // The shared ``baseStyles.header`` is absolutely positioned at
    // top: 200 with a ~25pt-tall title (footprint ~200–225).
    // ``baseStyles.table`` has marginTop 0, so this spacer is the ONLY
    // thing pushing the following content clear of the title. It matches
    // the delivery-note / invoice PDFs' ``marginTop: 40`` so all three
    // reseller documents share the same relative layout below the title —
    // and so a document with EMPTY entry lines (spacer only) still clears
    // the title instead of riding up under it. (Was 10, which left the
    // offers table crowding the title's lower edge.)
    entryBlock: {
      width: "100%",
      marginTop: 40,
    },
    col1: { ...cellBase, width: "18%", textAlign: "left" },
    col2: { ...cellBase, width: "19%", textAlign: "left" },
    col3: { ...cellBase, width: "15%", textAlign: "right" },
    col5: { ...cellBase, width: "10%", textAlign: "right" },
    col6: { ...cellBase, width: "10%", textAlign: "right" },
    col7: { ...cellBase, width: "10%", textAlign: "right" },
    // Visual affordance: this is the column where the customer fills
    // in their order quantity by hand on the printed offer. The gray
    // fill makes it pop as "write here", and it's the one place we
    // deliberately depart from the otherwise-shared DN/Invoice table
    // style. The 5pt left margin pushes it off its neighbor so the
    // gray block reads as a distinct input box, not as a stretched
    // last column.
    col8: {
      ...cellBase,
      width: "18%",
      textAlign: "center",
      backgroundColor: "#f0f0f0",
      marginLeft: 5,
    },
    unitLabel: {
      fontSize: 8,
      color: "#666",
    },
  }),
};

interface OfferItem {
  share_article_name?: string;
  size?: string;
  sort?: string;
  description?: string;
  amount_per_pu?: number | string;
  unit?: string;
  price_1?: number | string | null;
  price_2?: number | string | null;
  price_3?: number | string | null;
  /** Flowed through ``OfferSerializer.organic_status`` (sourced from
   * ``share_article.organic_status``). Drives the bio legend at the
   * bottom of the offer document. */
  organic_status?: OrganicStatus;
}

interface LineSettings {
  entry_line_1_offer_reseller?: string;
  entry_line_2_offer_reseller?: string;
  entry_line_3_offer_reseller?: string;
  // Free-form ordering instructions, rendered between the entry lines
  // and the offers table. Single rich-text block (not three slots like
  // the entry/greeting groups).
  order_instructions_offer_reseller?: string;
  greeting_line_1_offer_reseller?: string;
  greeting_line_2_offer_reseller?: string;
  greeting_line_3_offer_reseller?: string;
}

export interface OfferPDFData {
  offers: OfferItem[];
  year: number;
  delivery_week: number;
  offer_group?: string;
}

interface OfferPDFProps {
  data: OfferPDFData;
  t: TFunction;
  footerSettings?: FooterSettings;
  lineSettings?: LineSettings;
  tenantSettings: TenantPDFSettings;
  resellerInfo?: ResellerInfo | null;
  resellers?: ResellerInfo[];
  tierLabels?: string[];
  pricesPerPU?: boolean;
  currencySymbol?: string;
  /**
   * Display date format threaded from the caller's ``useDateFormat()``;
   * default keeps legacy ``DD.MM.YYYY``.
   */
  dateFormat?: string;
  /**
   * Preview mode: render a bordered ``LOGO`` placeholder when the
   * tenant has no logo set. Used by the
   * ``ConfigurationResellerDocuments`` sample buttons so a brand-new
   * tenant can still see the document layout.
   */
  previewMode?: boolean;
}

function OfferPage({
  data,
  t,
  footerSettings,
  lineSettings,
  tenantSettings,
  resellerInfo,
  tierLabels = ["T1", "T3", "T5"],
  pricesPerPU = false,
  currencySymbol = "€",
  dateFormat = "DD.MM.YYYY",
  previewMode = false,
}: Omit<OfferPDFProps, "resellers">) {
  const { offers, delivery_week } = data;
  const locale = tenantSettings?.number_locale ?? "de-DE";
  const { getUnitLabel } = useUnitOptions();
  const { getVegetableSizeLabel } = useVegetableSizeOptions();

  const formatPrice = (
    price: number | string | null | undefined,
    amountPerPu?: number | string,
  ) => {
    if (
      price === null ||
      price === undefined ||
      price === "" ||
      Number(price) === 0
    )
      return "";
    const unitPrice = Number(price);
    const displayPrice =
      pricesPerPU && amountPerPu ? unitPrice * Number(amountPerPu) : unitPrice;
    return formatNumber(displayPrice, 2, locale);
  };

  // Tier columns are positional: ``price_1`` is the first configured
  // tier (``used_tiers_for_offers[0]``), ``price_2`` the second, etc.
  // ``tierLabels`` is derived from the LIVE setting in
  // ``OfferPDFGenerator``, so its length is the source of truth for
  // how many tier columns the tenant currently wants — even if the
  // historical ``Offer`` rows still carry data in the now-dropped
  // slots. Without this gate, removing a tier would silently leave a
  // label-less price column in re-rendered PDFs.
  const tier1Configured = tierLabels.length >= 1;
  const tier2Configured = tierLabels.length >= 2;
  const tier3Configured = tierLabels.length >= 3;

  // Filter out rows where all CURRENTLY-CONFIGURED tier prices are 0
  // or empty. A row whose only non-zero price sat in a dropped tier
  // disappears entirely, rather than rendering with all price cells
  // empty.
  const filteredOffers = offers?.filter((o) => {
    const p1 = tier1Configured && o.price_1 != null && Number(o.price_1) !== 0;
    const p2 = tier2Configured && o.price_2 != null && Number(o.price_2) !== 0;
    const p3 = tier3Configured && o.price_3 != null && Number(o.price_3) !== 0;
    return p1 || p2 || p3;
  });

  // Show a tier column only when (a) the tenant currently configures
  // it AND (b) at least one row has a non-zero price for it.
  const hasPrice1 =
    tier1Configured &&
    filteredOffers?.some((o) => o.price_1 != null && Number(o.price_1) !== 0);
  const hasPrice2 =
    tier2Configured &&
    filteredOffers?.some((o) => o.price_2 != null && Number(o.price_2) !== 0);
  const hasPrice3 =
    tier3Configured &&
    filteredOffers?.some((o) => o.price_3 != null && Number(o.price_3) !== 0);
  const visibleTiers = [hasPrice1, hasPrice2, hasPrice3].filter(Boolean).length;
  // Redistribute width from hidden tier columns
  // With all 3 tiers: 18+19+15+10+10+10+18 = 100%
  const extraWidth = (3 - visibleTiers) * 10;
  const col1Width = 18 + Math.floor(extraWidth / 2);
  const col2Width = 19 + Math.ceil(extraWidth / 2);

  const dynStyles = StyleSheet.create({
    dynCol1: {
      ...cellBase,
      width: `${col1Width}%`,
      textAlign: "left" as const,
    },
    dynCol2: { ...cellBase, width: `${col2Width}%`, paddingLeft: 3 },
  });

  const priceHeaderUnit = pricesPerPU
    ? `${currencySymbol}/${t("commissioning.pu")}`
    : currencySymbol;

  return (
    <Page size="A4" style={styles.page}>
      <PDFLogo tenantSettings={tenantSettings} placeholder={previewMode} />

      {resellerInfo && (
        <PDFResellerInfo
          tenantSettings={tenantSettings}
          resellerInfo={resellerInfo}
        />
      )}

      <PDFTenantInfo tenantSettings={tenantSettings}>
        <Text style={styles.label}>
          {t("commissioning.date")}: {dayjs().format(dateFormat)}
        </Text>
      </PDFTenantInfo>

      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.title}>
          {t("commissioning.offer")} {t("commissioning.KW")} {delivery_week}
        </Text>
      </View>

      {/* Entry lines + order instructions, both pushed below the
          absolutely-positioned title via the ``entryBlock`` spacer. */}
      {lineSettings && (
        <View style={styles.entryBlock}>
          <PDFEntryLines
            lines={[
              lineSettings.entry_line_1_offer_reseller,
              lineSettings.entry_line_2_offer_reseller,
              lineSettings.entry_line_3_offer_reseller,
            ]}
          />
          <PDFEntryLines
            lines={[lineSettings.order_instructions_offer_reseller]}
          />
        </View>
      )}

      {/* Offers Table */}
      <View style={styles.table}>
        <View style={styles.tableHeader} fixed>
          <Text style={dynStyles.dynCol1}>
            {t("commissioning.share_article_name")}
          </Text>
          <Text style={dynStyles.dynCol2}>
            {t("commissioning.description")}
          </Text>
          <Text style={styles.col3}>{t("commissioning.amount_per_pu")}</Text>
          {hasPrice1 && (
            <Text style={styles.col5}>
              {tierLabels[0]}
              <Text style={styles.unitLabel}>
                {"\n"}
                {priceHeaderUnit}
              </Text>
            </Text>
          )}
          {hasPrice2 && (
            <Text style={styles.col6}>
              {tierLabels[1]}
              <Text style={styles.unitLabel}>
                {"\n"}
                {priceHeaderUnit}
              </Text>
            </Text>
          )}
          {hasPrice3 && (
            <Text style={styles.col7}>
              {tierLabels[2]}
              <Text style={styles.unitLabel}>
                {"\n"}
                {priceHeaderUnit}
              </Text>
            </Text>
          )}
          <Text style={styles.col8}>
            {t("commissioning.ordering_amount_in_pu")}
          </Text>
        </View>

        {filteredOffers?.map((offer, index) => (
          <View key={index} style={styles.tableRow} wrap={false}>
            <Text style={dynStyles.dynCol1}>
              {offer.share_article_name}
              {offer.size !== "M" ? ", " + getVegetableSizeLabel(offer.size ?? "") : ""}
              {tenantSettings.organic_control_number
                ? organicMarker(offer.organic_status)
                : ""}
            </Text>
            <Text style={dynStyles.dynCol2}>
              {offer.sort} {offer.description}
            </Text>
            <Text style={styles.col3}>
              {formatNumber(offer.amount_per_pu, 2, locale)}{" "}
              <Text style={styles.unitLabel}>
                {getUnitLabel(offer.unit ?? "")}/{t("commissioning.pu")}
              </Text>
            </Text>
            {hasPrice1 && (
              <Text style={styles.col5}>
                {formatPrice(offer.price_1, offer.amount_per_pu)}
                {!pricesPerPU &&
                formatPrice(offer.price_1, offer.amount_per_pu) ? (
                  <Text style={styles.unitLabel}>
                    /{getUnitLabel(offer.unit ?? "")}
                  </Text>
                ) : null}
              </Text>
            )}
            {hasPrice2 && (
              <Text style={styles.col6}>
                {formatPrice(offer.price_2, offer.amount_per_pu)}
                {!pricesPerPU &&
                formatPrice(offer.price_2, offer.amount_per_pu) ? (
                  <Text style={styles.unitLabel}>
                    /{getUnitLabel(offer.unit ?? "")}
                  </Text>
                ) : null}
              </Text>
            )}
            {hasPrice3 && (
              <Text style={styles.col7}>
                {formatPrice(offer.price_3, offer.amount_per_pu)}
                {!pricesPerPU &&
                formatPrice(offer.price_3, offer.amount_per_pu) ? (
                  <Text style={styles.unitLabel}>
                    /{getUnitLabel(offer.unit ?? "")}
                  </Text>
                ) : null}
              </Text>
            )}
            <Text style={styles.col8}></Text>
          </View>
        ))}
      </View>

      <PDFOrganicFooter
        tenantSettings={tenantSettings}
        lineItems={offers as unknown as LineItemBase[]}
        t={t}
      />

      {/* Greeting Lines */}
      {lineSettings && (
        <PDFGreetingLines
          lines={[
            lineSettings.greeting_line_1_offer_reseller,
            lineSettings.greeting_line_2_offer_reseller,
            lineSettings.greeting_line_3_offer_reseller,
          ]}
        />
      )}

      <PDFFooter footerSettings={footerSettings} />
    </Page>
  );
}

export default function OfferPDF({
  data,
  t,
  footerSettings,
  lineSettings,
  tenantSettings,
  resellerInfo,
  resellers,
  tierLabels = ["T1", "T3", "T5"],
  pricesPerPU = false,
  currencySymbol = "€",
  dateFormat = "DD.MM.YYYY",
  previewMode = false,
}: OfferPDFProps) {
  const pageProps = {
    data,
    t,
    footerSettings,
    lineSettings,
    tenantSettings,
    tierLabels,
    pricesPerPU,
    currencySymbol,
    dateFormat,
    previewMode,
  };

  if (resellers && resellers.length > 0) {
    return (
      <Document>
        {resellers.map((reseller, idx) => (
          <OfferPage key={idx} {...pageProps} resellerInfo={reseller} />
        ))}
      </Document>
    );
  }

  return (
    <Document>
      <OfferPage {...pageProps} resellerInfo={resellerInfo} />
    </Document>
  );
}
