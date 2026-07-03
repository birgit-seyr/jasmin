import { PDFViewer } from "@react-pdf/renderer";
import { Button, Spin } from "antd";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useCommissioningDeliveryNotesRetrieve } from "@shared/api/generated/commissioning/commissioning";
import { useDateFormat } from "@hooks/index";
import { useTenant } from "@hooks/configuration/useTenant";
import DeliveryNotePDF from "./DeliveryNotePDF";
import { useResellerPdfContext } from "./resellerPdfContext";
import { buildDeliveryNotePdfData } from "./resellerPdfData";

// ``generateAndUploadDeliveryNotePDF`` was moved to
// ``./generateDeliveryNotePDF.tsx`` in the 2026-06 lazy-loading pass.
// Its file does NOT have a top-level @react-pdf/renderer import, so
// consumers that only need the upload helper (Invoices.tsx,
// DeliveryNotes.tsx, useOrdersData.ts) keep the ~484 KB gzip PDF chunk
// out of their eager bundle. The barrel ``components/pdfs/index.ts``
// re-exports the helper from its new location.
//
// THIS file (DeliveryNotePDFGenerator.tsx) still carries the static
// @react-pdf import because the React component below renders
// ``<PDFViewer>`` and ``<DeliveryNotePDF>`` at mount time. Wrap with
// ``React.lazy`` at call sites to keep IT out of the eager bundle.

interface DeliveryNotePDFGeneratorProps {
  deliveryNoteId: string | null;
  buttonText?: string;
  buttonSize?: "small" | "middle" | "large";
  viewMode?: boolean;
}

export default function DeliveryNotePDFGenerator({
  deliveryNoteId,
  buttonText,
  buttonSize = "middle",
  viewMode = false,
}: DeliveryNotePDFGeneratorProps) {
  const { t } = useTranslation();
  const { tenant, getSetting, logoUrl, bioLogoUrl } = useTenant();
  const { dateFormat } = useDateFormat();
  const { tenantSettings, footerSettings, currencySymbol, lineSettings } =
    useResellerPdfContext({
      tenant: tenant as Record<string, unknown>,
      getSetting,
      logoUrl,
      bioLogoUrl,
      docType: "delivery_note",
    });

  const {
    data: deliveryNoteData,
    isLoading: loading,
    error: queryError,
  } = useCommissioningDeliveryNotesRetrieve(deliveryNoteId!, {
    query: { enabled: !!deliveryNoteId },
  });

  // ``queryError`` is now typed as ``ErrorResponse`` (the canonical
  // shape injected by ``core.openapi.inject_canonical_error_responses``)
  // rather than ``Error``. ``message`` is on both shapes — read it
  // directly and fall back to the generic copy.
  const error = queryError
    ? queryError.message || "Failed to load delivery note data"
    : null;

  const pdfData = useMemo(
    () =>
      deliveryNoteData ? buildDeliveryNotePdfData(deliveryNoteData) : null,
    [deliveryNoteData],
  );

  const storedFileUrl = deliveryNoteData?.file ?? null;

  if (loading) return <Spin />;

  if (error) {
    return (
      <div style={{ color: "var(--color-error)" }}>
        {t("common.error")}: {error}
      </div>
    );
  }

  if (!pdfData) return null;

  const pdfComponent = (
    <DeliveryNotePDF
      data={pdfData}
      t={t}
      footerSettings={footerSettings}
      lineSettings={lineSettings}
      tenantSettings={tenantSettings}
      currencySymbol={currencySymbol}
      dateFormat={dateFormat}
    />
  );

  const handlePDFDownload = () => {
    if (!storedFileUrl) return;
    window.open(storedFileUrl, "_blank", "noopener,noreferrer");
  };

  if (viewMode) {
    return (
      <div style={{ width: "100%", height: "800px" }}>
        <PDFViewer width="100%" height="100%">
          {pdfComponent}
        </PDFViewer>
      </div>
    );
  }

  return (
    <Button
      type="primary"
      size={buttonSize}
      onClick={handlePDFDownload}
      disabled={!storedFileUrl}
    >
      {buttonText || t("commissioning.download_pdf")}
    </Button>
  );
}
