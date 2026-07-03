/**
 * Shared download flows for the stored reseller invoice documents, used by both
 * ``InvoicePDFButtons`` (lazy, toast errors) and ``InvoicePDFGenerator``
 * (eager, disabled-button errors). Each component keeps its own loading/error
 * UI; only the fetch-embed-download mechanics + filename live here.
 */

import type { TFunction } from "i18next";
import { downloadBlob } from "@shared/utils";
import { embedZUGFeRDXML } from "../zugferd";

/** Canonical reseller-document PDF filename: ``<Label>-<prefix>-<number>.pdf``.
 * A storno / correction is labeled "Storno-Rechnung", not "Rechnung", so a
 * cancellation isn't named like a regular invoice. */
export function invoicePdfFilename(
  t: TFunction,
  prefix: string | number | null | undefined,
  number: string | number | null | undefined,
  documentType?: string | null,
): string {
  const isStorno =
    documentType === "storno" || documentType === "correction";
  const label = isStorno
    ? t("commissioning.storno_invoice_title")
    : t("commissioning.invoice");
  return `${label}-${prefix}-${number}.pdf`;
}

/** Open an already-stored PDF in a new browser tab. */
export function openStoredPdf(url: string): void {
  window.open(url, "_blank", "noopener,noreferrer");
}

/**
 * Fetch the stored invoice PDF + XML, embed the XML to produce a ZUGFeRD
 * e-invoice PDF, and trigger its download. Callers null-check the URLs and
 * surface failures themselves; this throws on fetch/embed errors.
 */
export async function downloadZugferd(
  storedFileUrl: string,
  storedXmlUrl: string,
  filename: string,
): Promise<void> {
  const [pdfResponse, xmlResponse] = await Promise.all([
    fetch(storedFileUrl),
    fetch(storedXmlUrl),
  ]);
  const pdfBlob = await pdfResponse.blob();
  const xmlString = await xmlResponse.text();
  const zugferdBlob = await embedZUGFeRDXML(pdfBlob, xmlString);
  downloadBlob(zugferdBlob, filename);
}
