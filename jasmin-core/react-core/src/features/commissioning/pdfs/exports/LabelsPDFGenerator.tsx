import { useCallback } from "react";
import {
  isImageField,
  labelElementText,
  showsImage,
  type LabelData,
  type LabelFarm,
  type LabelLayout,
} from "@features/commissioning/utils/labelLayout";
import ListPDFGenerator from "./ListPDFGenerator";
import type { LabelsPDFProps, PrintedLabel } from "./LabelsPDF";

interface LabelsPDFGeneratorProps {
  /** Null keeps the button disabled, as does an empty list of labels. */
  layout: LabelLayout | null;
  labels: LabelData[];
  farm: LabelFarm;
  logoUrl: string | null;
  bioLogoUrl: string | null;
  startPosition?: number;
  filename: string;
  buttonText: string;
}

/** The images the layout places, loaded once for every label: the logos as
 *  data URLs, each QR code drawn from its text. Both helpers load on the
 *  click, like the PDF library they come with. */
async function loadImages(
  layout: LabelLayout,
  logoUrl: string | null,
  bioLogoUrl: string | null,
): Promise<Record<string, string | null>> {
  const { convertLogoToBase64 } = await import("../forResellers/pdfBase");
  const images: Record<string, string | null> = {};
  const fields = new Set(layout.elements.map((element) => element.field));
  const [farmLogo, organicLogo] = await Promise.all([
    fields.has("farm_logo") && logoUrl ? convertLogoToBase64(logoUrl) : null,
    fields.has("organic_logo") && bioLogoUrl ? convertLogoToBase64(bioLogoUrl) : null,
  ]);
  const qrElements = layout.elements.filter(
    (element) => element.field === "qr_code" && element.text.trim(),
  );
  const QRCode = qrElements.length ? (await import("qrcode")).default : null;
  for (const element of layout.elements) {
    if (element.field === "farm_logo") images[element.id] = farmLogo;
    if (element.field === "organic_logo") images[element.id] = organicLogo;
  }
  for (const element of qrElements) {
    images[element.id] = await QRCode!.toDataURL(element.text, {
      errorCorrectionLevel: "M",
      margin: 0,
      width: 300,
    });
  }
  return images;
}

export default function LabelsPDFGenerator({
  layout,
  labels,
  farm,
  logoUrl,
  bioLogoUrl,
  startPosition,
  filename,
  buttonText,
}: LabelsPDFGeneratorProps) {
  const loadDocumentProps = useCallback(async (): Promise<LabelsPDFProps> => {
    const images = await loadImages(layout!, logoUrl, bioLogoUrl);
    const printed: PrintedLabel[] = labels.map((label) => {
      const values: PrintedLabel = {};
      for (const element of layout!.elements) {
        const value = isImageField(element.field)
          ? showsImage(element, label, farm)
            ? images[element.id]
            : null
          : labelElementText(element, label, farm);
        if (value) values[element.id] = value;
      }
      return values;
    });
    return { layout: layout!, labels: printed, startPosition };
  }, [layout, labels, farm, logoUrl, bioLogoUrl, startPosition]);

  return (
    <ListPDFGenerator
      data={labels}
      isReady={layout !== null}
      filename={filename}
      buttonText={buttonText}
      documentLoader={() => import("./LabelsPDF")}
      documentProps={loadDocumentProps}
    />
  );
}
