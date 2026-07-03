import { Button } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { commissioningInvoicesRetrieve } from "@shared/api/generated/commissioning/commissioning";
import { notify } from "@shared/utils";
import { downloadZugferd, invoicePdfFilename, openStoredPdf } from "./pdfDownload";

/**
 * Lightweight invoice download buttons.
 *
 * Unlike `InvoicePDFGenerator` (which fetches the invoice + builds a QR
 * code + converts the logo on mount so it can show a `<PDFViewer>` in
 * `viewMode`), this component does NO work until the user actually clicks
 * a button. Use it inside table rows / lists where each row would
 * otherwise trigger its own per-invoice request.
 *
 * Renders two buttons:
 *   - "PDF"     → opens the already-stored file URL in a new tab
 *   - "e-PDF"   → fetches PDF + XML blobs and combines them into ZUGFeRD
 */
interface InvoicePDFButtonsProps {
  invoiceId: string | null;
  buttonText?: string;
  buttonSize?: "small" | "middle" | "large";
}

export default function InvoicePDFButtons({
  invoiceId,
  buttonText,
  buttonSize = "middle",
}: InvoicePDFButtonsProps) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState<"none" | "pdf" | "zugferd">("none");

  const handlePDFDownload = async () => {
    if (!invoiceId) return;
    setBusy("pdf");
    try {
      const invoice = await commissioningInvoicesRetrieve(invoiceId);
      if (!invoice.file) {
        notify.error(t("commissioning.pdf_not_available"));
        return;
      }
      openStoredPdf(invoice.file);
    } catch (err) {
      console.error("Failed to load invoice for PDF download:", err);
      notify.error(t("common.error_loading_data"));
    } finally {
      setBusy("none");
    }
  };

  const handleZUGFeRDDownload = async () => {
    if (!invoiceId) return;
    setBusy("zugferd");
    try {
      const invoice = await commissioningInvoicesRetrieve(invoiceId);
      const storedFileUrl = invoice.file ?? null;
      const storedXmlUrl =
        ((invoice as unknown as Record<string, unknown>).xml_file as
          | string
          | undefined) ?? null;
      if (!storedFileUrl || !storedXmlUrl) {
        notify.error(
          t("commissioning.zugferd_not_available"),
        );
        return;
      }

      await downloadZugferd(
        storedFileUrl,
        storedXmlUrl,
        invoicePdfFilename(t, invoice.prefix, invoice.number, invoice.document_type),
      );
    } catch (err) {
      console.error("Failed to build ZUGFeRD download:", err);
      notify.error(t("common.error_loading_data"));
    } finally {
      setBusy("none");
    }
  };

  const disabled = !invoiceId || busy !== "none";

  return (
    <div style={{ display: "flex", gap: 8 }}>
      <Button
        type="primary"
        size={buttonSize}
        onClick={handlePDFDownload}
        loading={busy === "pdf"}
        disabled={disabled}
      >
        {buttonText || t("commissioning.download_pdf")}
      </Button>
      <Button
        type="primary"
        size={buttonSize}
        onClick={handleZUGFeRDDownload}
        loading={busy === "zugferd"}
        disabled={disabled}
      >
        {t("commissioning.download_zugferd")}
      </Button>
    </div>
  );
}
