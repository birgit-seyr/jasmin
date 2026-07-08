import type { TFunction } from "i18next";

import type { PackingBoxesMatrixColumn } from "@shared/api/generated/models";

import ListPDFGenerator from "./ListPDFGenerator";
import type { PackingBoxesMatrixPDFProps } from "./PackingBoxesMatrixPDF";

interface PackingBoxesMatrixPDFGeneratorProps {
  columns: PackingBoxesMatrixColumn[] | null;
  data: PackingBoxesMatrixPDFProps["data"] | null;
  week: number | null;
  dayName: string;
  showSize?: boolean;
  filename: string;
  buttonText: string;
  t: TFunction;
}

export default function PackingBoxesMatrixPDFGenerator({
  columns,
  data,
  week,
  dayName,
  showSize,
  filename,
  buttonText,
  t,
}: PackingBoxesMatrixPDFGeneratorProps) {
  return (
    <ListPDFGenerator
      data={data}
      isReady={!!columns && columns.length > 0}
      filename={filename}
      buttonText={buttonText}
      documentLoader={() => import("./PackingBoxesMatrixPDF")}
      documentProps={{
        columns: columns ?? [],
        data: data ?? [],
        week,
        dayName,
        showSize,
        t,
      }}
    />
  );
}
