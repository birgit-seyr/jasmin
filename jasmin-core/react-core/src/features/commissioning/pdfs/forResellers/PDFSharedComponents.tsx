import type { ReactNode } from "react";
import { Text, View, Image } from "@react-pdf/renderer";
import dayjs from "dayjs";
import type { TFunction } from "i18next";
import PDFRichText from "./PDFRichText";
import {
  baseStyles as styles,
  type FooterSettings,
  type LineItemBase,
  organicMarksPresent,
  type ResellerInfo,
  type TenantPDFSettings,
} from "./pdfBase";

// ─── Logo ───────────────────────────────────────────────────────────────────

export function PDFLogo({
  tenantSettings,
  placeholder = false,
}: {
  tenantSettings: TenantPDFSettings;
  /**
   * Render a bordered ``LOGO`` box when no logo file is set. Off by
   * default so production PDFs for tenants without a logo stay clean;
   * the preview buttons in
   * ``ConfigurationResellerDocuments`` opt in.
   */
  placeholder?: boolean;
}) {
  if (tenantSettings.logo) {
    return (
      <View style={styles.logoContainer}>
        <Image src={tenantSettings.logo} style={styles.logo} />
      </View>
    );
  }
  if (!placeholder) return null;
  return (
    <View
      style={[
        styles.logoContainer,
        {
          borderWidth: 1,
          borderColor: "#999",
          borderStyle: "dashed",
          alignItems: "center",
          justifyContent: "center",
        },
      ]}
    >
      <Text style={[styles.text_muted, { fontSize: 10, letterSpacing: 2 }]}>
        LOGO
      </Text>
    </View>
  );
}

// ─── Reseller address block ─────────────────────────────────────────────────

export function PDFResellerInfo({
  tenantSettings,
  resellerInfo,
}: {
  tenantSettings: TenantPDFSettings;
  resellerInfo: ResellerInfo;
}) {
  return (
    <View style={styles.resellerInfoContainer}>
      <Text style={styles.text_grey}>
        {tenantSettings.name} - {tenantSettings.address} -{" "}
        {tenantSettings.zip_code} {tenantSettings.city}
      </Text>
      <View style={styles.divider} />

      <Text style={styles.label}>{resellerInfo.reseller_name}</Text>
      {resellerInfo.reseller_address && (
        <Text style={styles.label}>{resellerInfo.reseller_address}</Text>
      )}
      <Text style={styles.label}>
        {resellerInfo.reseller_zip} {resellerInfo.reseller_city}
      </Text>
     
      {resellerInfo.reseller_uid && (
        <Text style={styles.label}>UID: {resellerInfo.reseller_uid}</Text>
      )}
    </View>
  );
}

// ─── Right-aligned tenant info ──────────────────────────────────────────────

interface PDFTenantInfoProps {
  tenantSettings: TenantPDFSettings;
  children?: ReactNode;
}

export function PDFTenantInfo({ tenantSettings, children }: PDFTenantInfoProps) {
  return (
    <View style={styles.section}>
      <Text style={styles.label}>{tenantSettings.name}</Text>
      <Text style={styles.label}>{tenantSettings.address}</Text>
      <Text style={styles.label}>
        {tenantSettings.zip_code} {tenantSettings.city}
      </Text>
      <Text style={styles.label}>
        {tenantSettings.email_for_orders || tenantSettings.email}
      </Text>
      <Text style={styles.label}>{tenantSettings.phone_number}</Text>
      {children}
    </View>
  );
}

// ─── Entry lines ────────────────────────────────────────────────────────────

export function PDFEntryLines({
  lines,
}: {
  lines: (string | undefined | null)[];
}) {
  const hasContent = lines.some((l) => l);
  if (!hasContent) return null;
  return (
    <View style={styles.entrySection}>
      {lines.map(
        (line, i) => line && <PDFRichText key={i} html={line} />,
      )}
    </View>
  );
}

// ─── Greeting lines ─────────────────────────────────────────────────────────

export function PDFGreetingLines({
  lines,
  children,
}: {
  lines: (string | undefined | null)[];
  children?: ReactNode;
}) {
  return (
    <View style={styles.greetingSection} wrap={false}>
      {lines.map(
        (line, i) => line && <PDFRichText key={i} html={line} />,
      )}
      {children}
    </View>
  );
}

// ─── Hash bar (finalized documents) ─────────────────────────────────────────

export function PDFHashBar({
  documentHash,
  finalizedAt,
  dateFormat = "DD.MM.YYYY",
  t,
}: {
  documentHash?: string;
  finalizedAt?: string | null;
  /** Tenant display date format, threaded from the caller. Default keeps the
   *  legacy DD.MM.YYYY. The time half stays HH:mm. */
  dateFormat?: string;
  t: TFunction;
}) {
  if (!documentHash) return null;
  return (
    <View style={styles.hashBar} fixed>
      <Text>
        {documentHash} |{" "}
        {finalizedAt ? dayjs(finalizedAt).format(`${dateFormat} HH:mm`) : ""}
      </Text>
      <Text
        render={({ pageNumber, totalPages }) =>
          `${t("common.page")} ${pageNumber} / ${totalPages}`
        }
      />
    </View>
  );
}

// ─── Organic disclosure footer ──────────────────────────────────────────────

/**
 * EU 2018/848 organic disclosure block: the tenant's ``bio_logo`` on
 * the left + one ``*`` line per organic mark actually present in the
 * line items on the right. Used by every reseller document (invoice,
 * delivery note, offer) to keep the legend identical across all three.
 *
 * Renders nothing when:
 *   * the tenant has no ``organic_control_number`` (not certified), OR
 *   * the line items contain no organic / in-conversion marks.
 *
 * Wrapped in ``wrap={false}`` so the logo + legend never split across
 * a page break.
 */
export function PDFOrganicFooter({
  tenantSettings,
  lineItems,
  t,
}: {
  tenantSettings: TenantPDFSettings;
  lineItems: LineItemBase[];
  t: TFunction;
}) {
  if (!tenantSettings.organic_control_number) return null;
  const { hasOrganic, hasInConversion } = organicMarksPresent(lineItems);
  if (!hasOrganic && !hasInConversion) return null;
  return (
    <View
      wrap={false}
      style={{
        marginTop: 8,
        marginBottom: 6,
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
      }}
    >
      {tenantSettings.bio_logo && (
        <Image
          src={tenantSettings.bio_logo}
          style={{ width: 40, height: 30, objectFit: "contain" }}
          cache={false}
        />
      )}
      <View style={{ flexGrow: 1 }}>
        {hasOrganic && (
          <Text style={{ fontSize: 9 }}>
            {`* ${t("commissioning.organic.organic_footer")}: ${tenantSettings.organic_control_number}`}
          </Text>
        )}
        {hasInConversion && (
          <Text style={{ fontSize: 9 }}>
            {`** ${t("commissioning.organic.in_conversion_footer")}: ${tenantSettings.organic_control_number}`}
          </Text>
        )}
      </View>
    </View>
  );
}

// ─── Footer ─────────────────────────────────────────────────────────────────

export function PDFFooter({
  footerSettings,
}: {
  footerSettings?: FooterSettings;
}) {
  if (!footerSettings) return null;
  return (
    <View style={styles.footer} fixed>
      <View style={[styles.footerColumn, styles.footerLeft]}>
        <PDFRichText
          html={footerSettings.left_column_footer_documents_reseller}
        />
      </View>
      <View style={[styles.footerColumn, styles.footerMiddle]}>
        <PDFRichText
          html={footerSettings.middle_column_footer_documents_reseller}
        />
      </View>
      <View style={[styles.footerColumn, styles.footerRight]}>
        <PDFRichText
          html={footerSettings.right_column_footer_documents_reseller}
        />
      </View>
    </View>
  );
}
