import type { TFunction } from "i18next";
import { commissioningInvoicesRetrieve } from "@shared/api/generated/commissioning/commissioning";
import type { ZipEntry } from "@shared/utils";
import { downloadRecordsZip } from "./bulkZip";
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
  await downloadRecordsZip({
    ids: invoiceIds,
    retrieve: commissioningInvoicesRetrieve,
    buildEntry: async (invoice): Promise<ZipEntry | null> => {
      // Only real e-PDFs qualify: a stored PDF (``file``) AND its ZUGFeRD XML.
      if (!invoice.file || !invoice.xml_file) return null;
      const blob = await buildZugferdBlob(invoice.file, invoice.xml_file);
      return {
        name: invoicePdfFilename(
          t,
          invoice.prefix,
          invoice.number,
          invoice.document_type,
        ),
        blob,
      };
    },
    emptyKey: "download.bulk_zip_no_finalized",
    skippedKey: "download.bulk_zip_some_skipped",
    zipFilename,
    t,
  });
}
