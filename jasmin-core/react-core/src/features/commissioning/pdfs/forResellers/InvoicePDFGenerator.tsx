import { PDFViewer } from "@react-pdf/renderer";
import { Button, Spin } from "antd";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCommissioningInvoicesRetrieve } from "@shared/api/generated/commissioning/commissioning";
import { useDateFormat } from "@hooks/index";
import { useTenant } from "@hooks/configuration/useTenant";
import { generatePaymentQRCode } from "../qrcodeGenerator";
import {
  downloadZugferd,
  invoicePdfFilename,
  openStoredPdf,
} from "./pdfDownload";
import InvoicePDF, { type InvoicePDFData } from "./InvoicePDF";
import { useResellerPdfContext } from "./resellerPdfContext";
import {
  buildBankDetails,
  buildInvoicePdfData,
  resolvePaymentTerms,
} from "./resellerPdfData";

// ``generateAndUploadInvoicePDF`` was moved to
// ``./generateInvoicePDF.tsx`` in the 2026-06 lazy-loading pass. Its
// file does NOT have a top-level @react-pdf/renderer import, so
// consumers that only need the upload helper (Invoices.tsx,
// useOrdersData.ts) keep the ~484 KB gzip PDF chunk out of their
// eager bundle. The barrel ``components/pdfs/index.ts`` re-exports
// the helper from its new location.
//
// THIS file (InvoicePDFGenerator.tsx) still carries the static
// @react-pdf import because the React component below renders
// ``<PDFViewer>`` and ``<InvoicePDF>`` at mount time. To keep it
// out of the eager bundle on consuming pages, wrap with
// ``React.lazy`` at the call site (InvoiceModal does this).

interface InvoicePDFGeneratorProps {
  invoiceId: string | null;
  buttonText?: string;
  buttonSize?: "small" | "middle" | "large";
  viewMode?: boolean;
}

export default function InvoicePDFGenerator({
  invoiceId,
  buttonText,
  buttonSize = "middle",
  viewMode = false,
}: InvoicePDFGeneratorProps) {
  const [qrCodeDataUrl, setQrCodeDataUrl] = useState<string | null>(null);

  const { t } = useTranslation();
  const { tenant, getSetting, logoUrl, bioLogoUrl } = useTenant();
  const { dateFormat } = useDateFormat();
  const { tenantSettings, footerSettings, currencySymbol, lineSettings } =
    useResellerPdfContext({
      tenant: tenant as Record<string, unknown>,
      getSetting,
      logoUrl,
      bioLogoUrl,
      docType: "invoice",
    });

  const bankDetails = useMemo(
    () => buildBankDetails(tenant as Record<string, unknown>),
    [tenant],
  );

  const {
    data: invoiceData,
    isLoading: loading,
    error: queryError,
  } = useCommissioningInvoicesRetrieve(invoiceId!, {
    query: { enabled: !!invoiceId },
  });

  const error = queryError
    ? queryError.message || "Failed to load invoice data"
    : null;

  const pdfData = useMemo<InvoicePDFData | null>(
    () => (invoiceData ? buildInvoicePdfData(invoiceData, bankDetails) : null),
    [invoiceData, bankDetails],
  );

  const storedFileUrl = invoiceData?.file ?? null;
  const storedXmlUrl = invoiceData?.xml_file ?? null;

  useEffect(() => {
    if (!pdfData) return;

    const processAsync = async () => {
      const qrCode = await generatePaymentQRCode(
        {
          prefix: pdfData.invoice.prefix,
          invoice_number: pdfData.invoice.invoice_number,
          total_brutto: pdfData.totals.brutto,
        },
        bankDetails,
        t,
      );
      setQrCodeDataUrl(qrCode);
    };

    processAsync();
  }, [pdfData, bankDetails, t]);

  if (loading) return <Spin />;

  if (error) {
    return (
      <div style={{ color: "var(--color-error)" }}>
        {t("common.error")}: {error}
      </div>
    );
  }

  if (!pdfData) return null;

  const fileName = invoicePdfFilename(
    t,
    pdfData.invoice.prefix,
    pdfData.invoice.invoice_number,
    pdfData.invoice.document_type,
  );

  // Per-invoice payment terms (per-reseller → tenant → hard-coded fallback).
  const paymentTerms = resolvePaymentTerms(invoiceData, getSetting);

  const pdfDocument = (
    <InvoicePDF
      data={pdfData}
      t={t}
      qrCodeDataUrl={qrCodeDataUrl}
      bankDetails={bankDetails}
      footerSettings={footerSettings}
      lineSettings={lineSettings}
      tenantSettings={tenantSettings}
      currencySymbol={currencySymbol}
      dateFormat={dateFormat}
      paymentTerms={paymentTerms}
    />
  );

  const handleZUGFeRDDownload = async () => {
    if (!storedFileUrl || !storedXmlUrl) return;
    await downloadZugferd(storedFileUrl, storedXmlUrl, fileName);
  };

  const handlePDFDownload = () => {
    if (!storedFileUrl) return;
    openStoredPdf(storedFileUrl);
  };

  if (viewMode) {
    return (
      <div style={{ width: "100%", height: "800px" }}>
        <PDFViewer width="100%" height="100%">
          {pdfDocument}
        </PDFViewer>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", gap: 8 }}>
      <Button
        type="primary"
        size={buttonSize}
        onClick={handlePDFDownload}
        disabled={!storedFileUrl}
      >
        {buttonText || t("commissioning.download_pdf")}
      </Button>
      <Button
        type="primary"
        size={buttonSize}
        onClick={handleZUGFeRDDownload}
        disabled={!storedFileUrl || !storedXmlUrl}
      >
        {t("commissioning.download_zugferd")}
      </Button>
    </div>
  );
}