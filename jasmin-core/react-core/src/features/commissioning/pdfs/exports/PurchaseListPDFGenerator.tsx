import ListPDFGenerator from "./ListPDFGenerator";

// ``BaseListPDF`` (the generic table PDF) is NOT statically imported —
// see ListPDFGenerator's docstring. The lazy factory keeps
// @react-pdf/renderer + the PDF template out of PurchaseList's
// eager bundle.

interface PurchaseListPDFGeneratorProps {
  data: Record<string, unknown>[] | null;
  title: string;
  subtitle: string;
  pill?: string;
  columns: unknown[];
  filename: string;
  buttonText: string;
}

export default function PurchaseListPDFGenerator({
  data,
  title,
  subtitle,
  pill,
  columns,
  filename,
  buttonText,
}: PurchaseListPDFGeneratorProps) {
  return (
    <ListPDFGenerator
      data={data}
      filename={filename}
      buttonText={buttonText}
      documentLoader={() => import("./BaseListPDF")}
      documentProps={{
        data: data ?? [],
        title,
        subtitle,
        pill,
        columns,
      }}
    />
  );
}
