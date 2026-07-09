/** Open an already-stored PDF (or any stored file URL) in a new browser tab.
 * No @react-pdf dependency — it only opens a URL — so it lives in the shared
 * utils layer and is reusable by any feature (reseller document buttons, the
 * customer documents card, …). */
export function openStoredPdf(url: string): void {
  window.open(url, "_blank", "noopener,noreferrer");
}
