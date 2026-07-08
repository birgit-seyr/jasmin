import type { TFunction } from "i18next";

import type { PackingBoxesMatrixColumn } from "@shared/api/generated/models";

import ListPDFGenerator from "./ListPDFGenerator";
import type { PackingBoxesMatrixPDFProps } from "./PackingBoxesMatrixPDF";
import type { TenantInfo } from "./ListPDFSharedComponents";

interface PackingBoxesMatrixPDFGeneratorProps {
  columns: PackingBoxesMatrixColumn[] | null;
  data: PackingBoxesMatrixPDFProps["data"] | null;
  week: number | null;
  dayName: string;
  showSize?: boolean;
  /** Optional brand strip — used by the member "Was ihr nehmen könnt" list. */
  tenant?: TenantInfo;
  /** Header pill key (defaults to the packing-boxes label in the PDF). */
  pillKey?: string;
  /** Render the per-combination count row (default true; off for the member
   *  per-share list). */
  showCountRow?: boolean;
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
  tenant,
  pillKey,
  showCountRow,
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
        tenant,
        pillKey,
        showCountRow,
        t,
      }}
    />
  );
}
