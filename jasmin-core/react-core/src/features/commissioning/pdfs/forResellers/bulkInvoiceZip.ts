import type { TFunction } from "i18next";
import { commissioningInvoicesRetrieve } from "@shared/api/generated/commissioning/commissioning";
import { downloadBlob, notify, zipFilesToBlob, type ZipEntry } from "@shared/utils";
import { buildZugferdBlob, invoicePdfFilename } from "./pdfDownload";

/**
 * Build a single ZIP of the finalized ZUGFeRD e-PDFs for the given invoices
 * and trigger its download.
 *
 * ``invoiceIds`` are invoices the caller already knows are finalized (the
 * Invoices page filters the selected rows by ``has_finalized_invoice``). Each
 * is fetched and only included when it actually carries BOTH a stored PDF
 * (``file``) and its ZUGFeRD XML (``xml_file``) — i.e. a real e-PDF, built the
 * same way the per-row "e-PDF" button builds it (fetch + embed via pdf-lib).
 * Invoices missing either half, or whose e-PDF can't be built, are skipped.
 * When nothing qualifies a subtle notice is shown instead of downloading an
 * empty archive.
 */
export async function downloadSelectedInvoiceEpdfsZip(
  invoiceIds: string[],
  t: TFunction,
  zipFilename: string,
): Promise<void> {
  if (invoiceIds.length === 0) {
    notify.info(t("download.bulk_zip_no_finalized"));
    return;
  }

  // Fetch the invoice records in parallel; a single failed lookup shouldn't
  // sink the whole batch, so null-out failures and count them as skipped.
  const invoices = await Promise.all(
    invoiceIds.map(async (id) => {
      try {
        return await commissioningInvoicesRetrieve(id);
      } catch (err) {
        console.error(`Failed to load invoice ${id} for bulk ZIP:`, err);
        return null;
      }
    }),
  );

  const entries: ZipEntry[] = [];
  let skipped = 0;

  for (const invoice of invoices) {
    if (!invoice || !invoice.file || !invoice.xml_file) {
      skipped += 1;
      continue;
    }
    try {
      const blob = await buildZugferdBlob(invoice.file, invoice.xml_file);
      entries.push({
        name: invoicePdfFilename(
          t,
          invoice.prefix,
          invoice.number,
          invoice.document_type,
        ),
        blob,
      });
    } catch (err) {
      console.error(`Failed to build e-PDF for invoice ${invoice.id}:`, err);
      skipped += 1;
    }
  }

  if (entries.length === 0) {
    notify.info(t("download.bulk_zip_no_finalized"));
    return;
  }

  const zipBlob = await zipFilesToBlob(entries);
  downloadBlob(zipBlob, zipFilename);

  if (skipped > 0) {
    notify.warning(t("download.bulk_zip_some_skipped", { count: skipped }));
  }
}
