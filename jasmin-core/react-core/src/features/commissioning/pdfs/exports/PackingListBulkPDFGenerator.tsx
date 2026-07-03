import type { TFunction } from "i18next";
import type { PackingListBulkItem } from "./PackingListBulkPDF";
import ListPDFGenerator from "./ListPDFGenerator";

interface PackingListBulkPDFGeneratorProps {
  data: PackingListBulkItem[] | null;
  year: number;
  week: number | null;
  dayName: string;
  shareType?: string;
  deliveryStationName?: string;
  showSize?: boolean;
  filename: string;
  buttonText: string;
  t: TFunction;
}

export default function PackingListBulkPDFGenerator({
  data,
  year,
  week,
  dayName,
  shareType,
  deliveryStationName,
  showSize,
  filename,
  buttonText,
  t,
}: PackingListBulkPDFGeneratorProps) {
  return (
    <ListPDFGenerator
      data={data}
      filename={filename}
      buttonText={buttonText}
      documentLoader={() => import("./PackingListBulkPDF")}
      documentProps={{
        data: data ?? [],
        year,
        week,
        dayName,
        shareType,
        deliveryStationName,
        showSize,
        t,
      }}
    />
  );
}
