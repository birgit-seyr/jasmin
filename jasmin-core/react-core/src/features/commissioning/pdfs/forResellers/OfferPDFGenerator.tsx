import { DownloadOutlined } from "@ant-design/icons";
import { PDFDownloadLink } from "@react-pdf/renderer";
import { Button, Spin } from "antd";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useCommissioningOffersList } from "@shared/api/generated/commissioning/commissioning";
import { useDateFormat, useTenant } from "@hooks/index";
import { formatWeekLabel, generatePdfFilename } from "@shared/utils";
import OfferPDF from "./OfferPDF";
import { type ResellerInfo } from "./pdfBase";
import { useResellerPdfContext } from "./resellerPdfContext";

interface OfferPDFGeneratorProps {
  year: number;
  delivery_week: number;
  offerGroupId: string;
  buttonText?: string;
  buttonSize?: "small" | "middle" | "large";
  viewMode?: boolean;
  resellerInfo?: ResellerInfo | null;
  resellers?: ResellerInfo[];
  pricesPerPU?: boolean;
}

export default function OfferPDFGenerator({
  year,
  delivery_week,
  offerGroupId,
  buttonText,
  buttonSize = "middle",
  resellerInfo,
  resellers,
  pricesPerPU = false,
}: OfferPDFGeneratorProps) {
  const { t } = useTranslation();
  const { tenant, getSetting, logoUrl, bioLogoUrl } = useTenant();
  const { dateFormat } = useDateFormat();
  const { tenantSettings, footerSettings, currencySymbol, lineSettings } =
    useResellerPdfContext({
      tenant: tenant as Record<string, unknown>,
      getSetting,
      logoUrl,
      bioLogoUrl,
      docType: "offer",
    });

  const used_tiers_for_offers = getSetting("used_tiers_for_offers") as
    | number[]
    | undefined;
  // Single-tier mode when the tenant hasn't configured tiers: the PDF
  // shows one price column (T1) only. No silent default to [1, 3, 5].
  const finalTiers =
    used_tiers_for_offers && used_tiers_for_offers.length > 0
      ? used_tiers_for_offers
      : [1];

  // Use same translation as Offers.tsx instead of hardcoded "T1", "T3", "T5"
  const tierLabels = finalTiers.map(
    (tier) => t("commissioning.tier", { tier }) || `T${tier}`,
  );

  const { data: offers, isLoading: loading, error: queryError } = useCommissioningOffersList(
    { year, delivery_week, offer_group: offerGroupId },
    { query: { enabled: !!offerGroupId } },
  );

  const error = useMemo(() => {
    if (queryError) return queryError.message || "Failed to load offer data";
    if (offers && offers.length === 0) return "No offers found";
    return null;
  }, [queryError, offers]);

  const pdfData = useMemo(() => {
    if (!offers || offers.length === 0) return null;
    return {
      offers,
      year,
      delivery_week,
      offer_group: offerGroupId,
    };
  }, [offers, year, delivery_week, offerGroupId]);

  if (loading) return <Spin />;

  if (error) {
    return (
      <div style={{ color: "var(--color-error)" }}>
        {t("common.error")}: {error}
      </div>
    );
  }

  if (!pdfData) return null;

  const fileName = `${generatePdfFilename([t("commissioning.offer"), year, formatWeekLabel(delivery_week, t), `OG${offerGroupId}`])}.pdf`;

  const pdfComponent = (
    <OfferPDF
      data={pdfData as never}
      t={t}
      resellerInfo={resellerInfo}
      resellers={resellers}
      tierLabels={tierLabels}
      footerSettings={footerSettings}
      lineSettings={lineSettings}
      tenantSettings={tenantSettings}
      currencySymbol={currencySymbol}
      dateFormat={dateFormat}
      pricesPerPU={pricesPerPU}
    />
  );

  return (
    <PDFDownloadLink
      document={pdfComponent}
      fileName={fileName}

      
    >
      <Button type="primary" size={buttonSize} icon={<DownloadOutlined />}>
        {buttonText || t("commissioning.download_pdf")}
      </Button>
    </PDFDownloadLink>
  );
}
