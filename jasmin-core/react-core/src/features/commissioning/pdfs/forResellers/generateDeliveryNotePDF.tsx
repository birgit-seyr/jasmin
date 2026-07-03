import type { TFunction } from "i18next";
import { commissioningDeliveryNotesRetrieve } from "@shared/api/generated/commissioning/commissioning";
import axiosService from "@shared/services/api";
import { buildResellerPdfContext } from "./resellerPdfContext";
import { buildDeliveryNotePdfData } from "./resellerPdfData";

/**
 * Standalone function to generate delivery note PDF and upload to the
 * backend. Called after finalization succeeds (Invoices.tsx,
 * DeliveryNotes.tsx, useOrdersData.ts bulk flow).
 *
 * Lazy-loading note: ``@react-pdf/renderer`` and the
 * ``DeliveryNotePDF`` document component are dynamic-imported inside
 * the function body. The exported file therefore does NOT carry
 * @react-pdf at parse time — consumers that only import this helper
 * keep the ~484 KB gzip PDF chunk out of their eager bundle.
 */
export async function generateAndUploadDeliveryNotePDF(
  deliveryNoteId: string,
  t: TFunction,
  tenant: Record<string, unknown>,
  getSetting: (key: string) => unknown,
  logoUrl: string | null | undefined,
  bioLogoUrl?: string | null,
): Promise<void> {
  const dnData = await commissioningDeliveryNotesRetrieve(deliveryNoteId);

  // Skip if already has stored file
  if (dnData.file) return;

  const { tenantSettings, footerSettings, currencySymbol, lineSettings } =
    await buildResellerPdfContext({
      tenant,
      getSetting,
      logoUrl,
      bioLogoUrl,
      docType: "delivery_note",
    });

  const pdfDataObj = buildDeliveryNotePdfData(dnData);
  const dateFormat = (getSetting("date_format") as string) || "DD.MM.YYYY";

  // LAZY IMPORTS — see generateInvoicePDF.tsx docstring for rationale.
  const [{ pdf }, { default: DeliveryNotePDF }] = await Promise.all([
    import("@react-pdf/renderer"),
    import("./DeliveryNotePDF"),
  ]);

  const pdfDocument = (
    <DeliveryNotePDF
      data={pdfDataObj}
      t={t}
      footerSettings={footerSettings}
      lineSettings={lineSettings}
      tenantSettings={tenantSettings}
      currencySymbol={currencySymbol}
      dateFormat={dateFormat}
    />
  );

  const fileName = `${t("commissioning.delivery_note")}-${pdfDataObj.deliveryNote.prefix}-${pdfDataObj.deliveryNote.delivery_note_number}.pdf`;

  const pdfBlob = await pdf(pdfDocument).toBlob();

  const formData = new FormData();
  formData.append("file", pdfBlob, fileName);
  await axiosService.post(
    `/api/commissioning/delivery_notes/${deliveryNoteId}/upload_pdf/`,
    formData,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
}
