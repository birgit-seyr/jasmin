/**
 * Trigger a browser download of the stored, byte-stable PDF for one
 * ConsentDocument version.
 *
 * The `download_pdf` endpoint is a public read (the PDF is the same policy text
 * as `retrieve`, with no member data) and responds with
 * `Content-Disposition: attachment`, so a plain same-origin link downloads it
 * directly — no auth header or blob handling needed.
 */
export function downloadConsentPdf(
  documentId: string | null | undefined,
): void {
  if (!documentId) return;
  const link = document.createElement("a");
  link.href = `/api/commissioning/consent_documents/${documentId}/download_pdf/`;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
}
