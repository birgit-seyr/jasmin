import type { TFunction } from "i18next";
import type { PackingListBulkPage } from "./PackingListBulkPDF";
import ListPDFGenerator from "./ListPDFGenerator";

interface PackingListBulkPDFGeneratorProps {
  /** One station per entry; null (or empty) keeps the button disabled. */
  pages: PackingListBulkPage[] | null;
  year: number;
  week: number | null;
  dayName: string;
  shareType?: string;
  showSize?: boolean;
  filename: string;
  buttonText: string;
  t: TFunction;
}

export default function PackingListBulkPDFGenerator({
  pages,
  year,
  week,
  dayName,
  shareType,
  showSize,
  filename,
  buttonText,
  t,
}: PackingListBulkPDFGeneratorProps) {
  return (
    <ListPDFGenerator
      data={pages}
      filename={filename}
      buttonText={buttonText}
      documentLoader={() => import("./PackingListBulkPDF")}
      documentProps={{
        pages: pages ?? [],
        year,
        week,
        dayName,
        shareType,
        showSize,
        t,
      }}
    />
  );
}
