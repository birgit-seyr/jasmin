import type { TFunction } from "i18next";
import { downloadBlob, notify, zipFilesToBlob, type ZipEntry } from "@shared/utils";

/**
 * Shared bulk-ZIP download orchestrator for the reseller documents (finalized
 * invoice e-PDFs, finalized delivery-note PDFs). One skeleton for both flows:
 *
 *   empty-input notice → fetch each record in parallel (null-on-error, skipped)
 *   → build a ``ZipEntry`` per record (``buildEntry`` returns ``null`` to skip a
 *   record that doesn't qualify, e.g. missing stored file) → empty-entries
 *   notice → ``zipFilesToBlob`` + ``downloadBlob`` → warn-on-skipped.
 *
 * Callers supply only the parts that differ: the ``retrieve`` loader, the
 * per-record ``buildEntry`` (retrieve/eligibility/filename), the i18n keys and
 * the zip filename. A single failed lookup or a failed ``buildEntry`` is
 * counted as a skip, never sinking the whole batch. Lives in its own
 * dependency-light module (only ``@shared/utils``) so the flow's heavier
 * pdf-lib / fflate deps stay confined to the per-flow wrappers.
 */
export async function downloadRecordsZip<T>({
  ids,
  retrieve,
  buildEntry,
  emptyKey,
  skippedKey,
  zipFilename,
  t,
}: {
  ids: string[];
  /** Fetch one record by id (throws on failure — counted as a skip). */
  retrieve: (id: string) => Promise<T>;
  /** Build the ZIP entry for a record, or ``null`` to skip it. May throw
   *  (counted as a skip). */
  buildEntry: (record: T) => Promise<ZipEntry | null> | ZipEntry | null;
  /** i18n key for the "nothing qualified" subtle info notice. */
  emptyKey: string;
  /** i18n key for the "N records were skipped" warning (gets ``{ count }``). */
  skippedKey: string;
  zipFilename: string;
  t: TFunction;
}): Promise<void> {
  if (ids.length === 0) {
    notify.info(t(emptyKey));
    return;
  }

  // Fetch the records in parallel; a single failed lookup shouldn't sink the
  // whole batch, so null-out failures and count them as skipped.
  const records = await Promise.all(
    ids.map(async (id) => {
      try {
        return await retrieve(id);
      } catch (err) {
        console.error(`Failed to load record ${id} for bulk ZIP:`, err);
        return null;
      }
    }),
  );

  const entries: ZipEntry[] = [];
  let skipped = 0;

  for (const record of records) {
    if (record === null) {
      skipped += 1;
      continue;
    }
    try {
      const entry = await buildEntry(record);
      if (entry === null) {
        skipped += 1;
        continue;
      }
      entries.push(entry);
    } catch (err) {
      console.error("Failed to build ZIP entry for a record:", err);
      skipped += 1;
    }
  }

  if (entries.length === 0) {
    notify.info(t(emptyKey));
    return;
  }

  const zipBlob = await zipFilesToBlob(entries);
  downloadBlob(zipBlob, zipFilename);

  if (skipped > 0) {
    notify.warning(t(skippedKey, { count: skipped }));
  }
}
