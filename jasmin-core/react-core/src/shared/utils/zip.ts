import type { Zippable } from "fflate";

/** A single file to place inside a ZIP archive. */
export interface ZipEntry {
  /** File name inside the archive, including its extension (e.g. ``Rechnung-RE-1.pdf``). */
  name: string;
  blob: Blob;
}

/**
 * Bundle a set of in-memory blobs into a single ZIP archive Blob.
 *
 * Uses the STORE method (``level: 0`` — no deflate) because the intended
 * payloads (PDFs, images) are already compressed, so a second pass only
 * burns CPU for no size win. Runs the archive build off the main thread via
 * fflate's async ``zip`` so a large bundle doesn't freeze the UI.
 *
 * fflate's runtime is dynamic-imported so it only loads when a bundle is
 * actually built (mirrors how ``embedZUGFeRDXML`` lazy-loads ``pdf-lib``) —
 * this keeps it out of the app-wide entry chunk despite the barrel
 * re-export. The ``Zippable`` type import is erased at compile time.
 *
 * Duplicate ``name``s are disambiguated with a ``(n)`` suffix so no entry is
 * silently dropped when the archive is opened.
 */
export async function zipFilesToBlob(entries: ZipEntry[]): Promise<Blob> {
  const { zip } = await import("fflate");

  const files: Zippable = {};
  const usedNames = new Set<string>();

  for (const entry of entries) {
    let name = entry.name;
    if (usedNames.has(name)) {
      const dot = name.lastIndexOf(".");
      const base = dot > 0 ? name.slice(0, dot) : name;
      const ext = dot > 0 ? name.slice(dot) : "";
      let counter = 2;
      while (usedNames.has(`${base}(${counter})${ext}`)) counter += 1;
      name = `${base}(${counter})${ext}`;
    }
    usedNames.add(name);
    files[name] = new Uint8Array(await entry.blob.arrayBuffer());
  }

  return new Promise<Blob>((resolve, reject) => {
    zip(files, { level: 0 }, (err, data) => {
      if (err) {
        reject(err);
        return;
      }
      resolve(new Blob([data], { type: "application/zip" }));
    });
  });
}
