import ListPDFGenerator from "./ListPDFGenerator";
import type { VariationTotal } from "./ListPDFSharedComponents";

// ``HarvestingListPDF`` is NOT statically imported — see
// ListPDFGenerator's docstring. The lazy factory keeps
// @react-pdf/renderer + the PDF template out of the eager bundle.

interface CrateData {
  crate_name?: string;
  quantity?: number;
}

interface HarvestingListPDFGeneratorProps {
  data: Record<string, unknown>[] | null;
  dataFirstPageOnly?: CrateData[] | null;
  variationsTotals?: VariationTotal[];
  title: string;
  subtitle: string;
  pill?: string;
  columns: unknown[];
  filename: string;
  buttonText: string;
}

export default function HarvestingListPDFGenerator({
  data,
  dataFirstPageOnly,
  variationsTotals,
  title,
  subtitle,
  pill,
  columns,
  filename,
  buttonText,
}: HarvestingListPDFGeneratorProps) {
  return (
    <ListPDFGenerator
      data={data}
      filename={filename}
      buttonText={buttonText}
      documentLoader={() => import("./HarvestingListPDF")}
      documentProps={{
        data: data ?? [],
        dataFirstPageOnly: dataFirstPageOnly ?? undefined,
        variationsTotals,
        title,
        subtitle,
        pill,
        columns,
      }}
    />
  );
}
