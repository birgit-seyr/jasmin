import type { TFunction } from "i18next";
import { commissioningDeliveryNotesRetrieve } from "@shared/api/generated/commissioning/commissioning";
import type { ZipEntry } from "@shared/utils";
import { downloadRecordsZip } from "./bulkZip";
import { deliveryNotePdfFilename } from "./pdfDownload";

/**
 * Build a single ZIP of the finalized delivery-note PDFs for the given
 * delivery notes and trigger its download.
 *
 * ``deliveryNoteIds`` are delivery notes the caller already knows are
 * finalized (the Delivery Notes page filters the selected rows by
 * ``delivery_note_is_finalized``). Each is fetched and only included when it
 * actually carries a stored PDF (``file``) — the canonical PDF that was
 * generated + uploaded at finalization and that the per-row download button
 * opens. Unlike invoices there is NO ZUGFeRD e-PDF step: delivery notes are
 * plain PDFs, so the stored file is used as-is (no client-side rebuild — the
 * stored document is the authoritative one the reseller received). Delivery
 * notes missing a stored file, or whose PDF can't be fetched, are skipped.
 * When nothing qualifies a subtle notice is shown instead of downloading an
 * empty archive.
 */
export async function downloadSelectedDeliveryNotePdfsZip(
  deliveryNoteIds: string[],
  t: TFunction,
  zipFilename: string,
): Promise<void> {
  await downloadRecordsZip({
    ids: deliveryNoteIds,
    retrieve: commissioningDeliveryNotesRetrieve,
    buildEntry: async (deliveryNote): Promise<ZipEntry | null> => {
      // Only delivery notes with a stored PDF qualify; the stored file is used
      // as-is (no client-side rebuild).
      if (!deliveryNote.file) return null;
      const response = await fetch(deliveryNote.file);
      const blob = await response.blob();
      return {
        name: deliveryNotePdfFilename(
          t,
          deliveryNote.prefix,
          deliveryNote.number,
        ),
        blob,
      };
    },
    emptyKey: "download.bulk_zip_no_finalized_delivery_notes",
    skippedKey: "download.bulk_zip_some_skipped_delivery_notes",
    zipFilename,
    t,
  });
}
