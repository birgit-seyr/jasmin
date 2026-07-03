import type { TFunction } from "i18next";
import type { CleaningListPDFProps } from "./CleaningListPDF";
import ListPDFGenerator from "./ListPDFGenerator";

// ``CleaningListPDF`` is NOT statically imported — it's dynamically
// loaded inside ListPDFGenerator's click handler. Keeps the PDF
// library out of this page's eager bundle. See ListPDFGenerator's
// docstring for the architecture.

interface CleaningListPDFGeneratorProps {
  data: CleaningListPDFProps["data"] | null;
  year: number;
  week: number;
  dayName: string;
  filename: string;
  buttonText: string;
  t: TFunction;
}

export default function CleaningListPDFGenerator({
  data,
  year,
  week,
  dayName,
  filename,
  buttonText,
  t,
}: CleaningListPDFGeneratorProps) {
  return (
    <ListPDFGenerator
      data={data}
      filename={filename}
      buttonText={buttonText}
      documentLoader={() => import("./CleaningListPDF")}
      // ``data ?? []`` coerces the wrapper-input nullable shape into
      // the document's required ``T[]``. ListPDFGenerator disables the
      // button when ``data`` is null/undefined, so the loader never
      // fires with empty data at runtime — the coercion just satisfies
      // the type system.
      documentProps={{ data: data ?? [], year, week, dayName, t }}
    />
  );
}
