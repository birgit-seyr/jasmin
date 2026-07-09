import type { TFunction } from "i18next";
import { commissioningInvoicesRetrieve } from "@shared/api/generated/commissioning/commissioning";
import axiosService from "@shared/services/api";
import { generatePaymentQRCode } from "../qrcodeGenerator";
import { generateZUGFeRDXML } from "../zugferd";
import { isCreditNote } from "./pdfBase";
import { buildResellerPdfContext } from "./resellerPdfContext";
import {
  buildBankDetails,
  buildInvoicePdfData,
  resolvePaymentTerms,
} from "./resellerPdfData";

/**
 * Standalone function to generate invoice PDF + XML and upload both
 * to the backend. Called from Invoices.tsx after finalization succeeds,
 * and from useOrdersData.ts in the bulk-finalize flow.
 *
 * Lazy-loading note: ``@react-pdf/renderer`` and the ``InvoicePDF``
 * document component are dynamic-imported inside the function body.
 * The exported file therefore does NOT carry @react-pdf at parse time —
 * any consumer that only imports this helper (and not the React-component
 * generator) keeps the ~484 KB gzip PDF chunk OUT of its eager bundle.
 *
 * The React-component generator (``InvoicePDFGenerator``) lives in
 * its own file (``InvoicePDFGenerator.tsx``) and is itself meant to
 * be wrapped with ``React.lazy`` at call sites — same idea, applied
 * at the component level instead of the function level.
 */
export async function generateAndUploadInvoicePDF(
  invoiceId: string,
  t: TFunction,
  tenant: Record<string, unknown>,
  getSetting: (key: string) => unknown,
  logoUrl: string | null | undefined,
  bioLogoUrl?: string | null,
): Promise<void> {
  const invoiceData = await commissioningInvoicesRetrieve(invoiceId);

  // Skip if already has stored files
  if (invoiceData.file) {
    return;
  }

  const bankDetails = buildBankDetails(tenant);
  const pdfDataObj = buildInvoicePdfData(invoiceData, bankDetails);

  const { tenantSettings, footerSettings, currencySymbol, lineSettings } =
    await buildResellerPdfContext({
      tenant,
      getSetting,
      logoUrl,
      bioLogoUrl,
      docType: "invoice",
    });
  // ISO currency code for the embedded ZUGFeRD XML (the printed symbol
  // comes from ``currencySymbol`` above). Default ``"EUR"`` matches the
  // legacy behavior for callers that never moved off the field default.
  const currencyCode = (getSetting("currency") as string) || "EUR";
  const dateFormat = (getSetting("date_format") as string) || "DD.MM.YYYY";

  // Per-invoice payment terms (per-reseller → tenant → hard-coded fallback).
  const paymentTerms = resolvePaymentTerms(invoiceData, getSetting);

  const qrCode = await generatePaymentQRCode(
    {
      prefix: pdfDataObj.invoice.prefix,
      invoice_number: pdfDataObj.invoice.invoice_number,
      total_brutto: pdfDataObj.totals.brutto,
    },
    bankDetails,
    t,
  );

  // LAZY IMPORTS — both @react-pdf/renderer and the InvoicePDF document
  // template load only when this function is actually called. Parallel
  // since they're independent.
  const [{ pdf }, { default: InvoicePDF }] = await Promise.all([
    import("@react-pdf/renderer"),
    import("./InvoicePDF"),
  ]);

  const pdfDocument = (
    <InvoicePDF
      data={pdfDataObj}
      t={t}
      qrCodeDataUrl={qrCode}
      bankDetails={bankDetails}
      footerSettings={footerSettings}
      lineSettings={lineSettings}
      tenantSettings={tenantSettings}
      currencySymbol={currencySymbol}
      dateFormat={dateFormat}
      paymentTerms={paymentTerms}
    />
  );

  // A storno / correction is stored (and emailed) as "Storno-Rechnung-…",
  // not "Rechnung-…", so the reseller's cancellation attachment isn't named
  // like a regular invoice.
  const docLabel = isCreditNote(pdfDataObj.invoice.document_type)
    ? t("commissioning.storno_invoice_title")
    : t("commissioning.invoice");
  const fileName = `${docLabel}-${pdfDataObj.invoice.prefix}-${pdfDataObj.invoice.invoice_number}.pdf`;
  const xmlFileName = `${docLabel}-${pdfDataObj.invoice.prefix}-${pdfDataObj.invoice.invoice_number}.xml`;

  // Generate PDF blob and XML string
  const pdfBlob = await pdf(pdfDocument).toBlob();
  const xmlString = generateZUGFeRDXML(
    pdfDataObj,
    bankDetails,
    tenantSettings,
    t,
    currencyCode,
    paymentTerms,
  );
  const xmlBlob = new Blob([xmlString], { type: "text/xml" });

  // Upload both to backend
  const formData = new FormData();
  formData.append("file", pdfBlob, fileName);
  formData.append("xml_file", xmlBlob, xmlFileName);
  await axiosService.post(
    `/api/commissioning/invoices/${invoiceId}/upload_pdf/`,
    formData,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
}
