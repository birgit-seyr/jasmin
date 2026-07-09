import type { TFunction } from "i18next";
import { commissioningDeliveryNotesRetrieve } from "@shared/api/generated/commissioning/commissioning";
import { downloadBlob, notify, zipFilesToBlob, type ZipEntry } from "@shared/utils";
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
  if (deliveryNoteIds.length === 0) {
    notify.info(t("download.bulk_zip_no_finalized_delivery_notes"));
    return;
  }

  // Fetch the delivery-note records in parallel; a single failed lookup
  // shouldn't sink the whole batch, so null-out failures and count them as
  // skipped.
  const deliveryNotes = await Promise.all(
    deliveryNoteIds.map(async (id) => {
      try {
        return await commissioningDeliveryNotesRetrieve(id);
      } catch (err) {
        console.error(`Failed to load delivery note ${id} for bulk ZIP:`, err);
        return null;
      }
    }),
  );

  const entries: ZipEntry[] = [];
  let skipped = 0;

  for (const deliveryNote of deliveryNotes) {
    if (!deliveryNote || !deliveryNote.file) {
      skipped += 1;
      continue;
    }
    try {
      const response = await fetch(deliveryNote.file);
      const blob = await response.blob();
      entries.push({
        name: deliveryNotePdfFilename(
          t,
          deliveryNote.prefix,
          deliveryNote.number,
        ),
        blob,
      });
    } catch (err) {
      console.error(
        `Failed to fetch PDF for delivery note ${deliveryNote.id}:`,
        err,
      );
      skipped += 1;
    }
  }

  if (entries.length === 0) {
    notify.info(t("download.bulk_zip_no_finalized_delivery_notes"));
    return;
  }

  const zipBlob = await zipFilesToBlob(entries);
  downloadBlob(zipBlob, zipFilename);

  if (skipped > 0) {
    notify.warning(
      t("download.bulk_zip_some_skipped_delivery_notes", { count: skipped }),
    );
  }
}
