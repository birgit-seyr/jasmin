import type { TFunction } from "i18next";
import type { WashingListPDFProps } from "./WashingListPDF";
import ListPDFGenerator from "./ListPDFGenerator";

interface WashingListPDFGeneratorProps {
  data: WashingListPDFProps["data"] | null;
  year: number;
  week: number;
  dayName: string;
  filename: string;
  buttonText: string;
  t: TFunction;
}

export default function WashingListPDFGenerator({
  data,
  year,
  week,
  dayName,
  filename,
  buttonText,
  t,
}: WashingListPDFGeneratorProps) {
  return (
    <ListPDFGenerator
      data={data}
      filename={filename}
      buttonText={buttonText}
      documentLoader={() => import("./WashingListPDF")}
      documentProps={{ data: data ?? [], year, week, dayName, t }}
    />
  );
}
