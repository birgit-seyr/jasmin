import type { TFunction } from "i18next";
import { useNumberFormat } from "@hooks/index";
import type { CommissioningListResellersPDFProps } from "./CommissioningListResellersPDF";
import ListPDFGenerator from "./ListPDFGenerator";

interface CommissioningListResellersPDFGeneratorProps {
  data: CommissioningListResellersPDFProps["data"] | null;
  year: number;
  week: number;
  dayName: string;
  filename: string;
  buttonText: string;
  t: TFunction;
}

export default function CommissioningListResellersPDFGenerator({
  data,
  year,
  week,
  dayName,
  filename,
  buttonText,
  t,
}: CommissioningListResellersPDFGeneratorProps) {
  const { locale } = useNumberFormat();
  return (
    <ListPDFGenerator
      data={data}
      filename={filename}
      buttonText={buttonText}
      documentLoader={() => import("./CommissioningListResellersPDF")}
      documentProps={{ data: data ?? [], year, week, dayName, t, locale }}
    />
  );
}
