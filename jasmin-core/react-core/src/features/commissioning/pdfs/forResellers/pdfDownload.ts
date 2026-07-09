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

/** Canonical reseller delivery-note PDF filename: ``<Label>-<prefix>-<number>.pdf``.
 * Mirrors ``invoicePdfFilename`` (delivery notes have no storno variant). Kept
 * next to it so both reseller-document filenames live in one place. */
export function deliveryNotePdfFilename(
  t: TFunction,
  prefix: string | number | null | undefined,
  number: string | number | null | undefined,
): string {
  return `${t("commissioning.delivery_note")}-${prefix}-${number}.pdf`;
}

/** Open an already-stored PDF in a new browser tab. */
export function openStoredPdf(url: string): void {
  window.open(url, "_blank", "noopener,noreferrer");
}

/**
 * Fetch the stored invoice PDF + XML and embed the XML to produce a ZUGFeRD
 * e-invoice PDF Blob (the "e-PDF"). Callers null-check the URLs and surface
 * failures themselves; this throws on fetch/embed errors. Split out from
 * ``downloadZugferd`` so the bulk-ZIP flow can collect the blob without
 * triggering a per-file browser download.
 */
export async function buildZugferdBlob(
  storedFileUrl: string,
  storedXmlUrl: string,
): Promise<Blob> {
  const [pdfResponse, xmlResponse] = await Promise.all([
    fetch(storedFileUrl),
    fetch(storedXmlUrl),
  ]);
  const pdfBlob = await pdfResponse.blob();
  const xmlString = await xmlResponse.text();
  return embedZUGFeRDXML(pdfBlob, xmlString);
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
  const zugferdBlob = await buildZugferdBlob(storedFileUrl, storedXmlUrl);
  downloadBlob(zugferdBlob, filename);
}
