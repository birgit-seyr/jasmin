/**
 * Trigger a browser "Save As" download for an in-memory Blob.
 *
 * The single home for the create-anchor → objectURL → click → revoke dance that
 * was previously copy-pasted across the PDF / CSV / VVT / MyData download sites.
 * The anchor is appended to the document before clicking (some browsers, incl.
 * Firefox, ignore synthetic clicks on a detached element) and removed again,
 * and the object URL is revoked afterwards to avoid leaking it.
 *
 * Callers pass the full filename including its extension (e.g. ``foo.pdf``).
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}
