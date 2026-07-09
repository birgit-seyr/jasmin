import type { TFunction } from "i18next";
import type { ArticleAmountTickListPDFProps } from "./ArticleAmountTickListPDF";
import ListPDFGenerator from "./ListPDFGenerator";

// ``ArticleAmountTickListPDF`` is NOT statically imported — it's dynamically
// loaded inside ListPDFGenerator's click handler. Keeps the PDF library out of
// this page's eager bundle. See ListPDFGenerator's docstring for the
// architecture. The washing / cleaning worksheets are the same document; the
// thin ``Washing``/``Cleaning`` wrappers pin the ``pillKey`` + ``amountAccessor``.

interface ArticleAmountTickListPDFGeneratorProps {
  data: ArticleAmountTickListPDFProps["data"] | null;
  year: number;
  week: number;
  dayName: string;
  filename: string;
  buttonText: string;
  pillKey: string;
  amountAccessor: ArticleAmountTickListPDFProps["amountAccessor"];
  t: TFunction;
}

export default function ArticleAmountTickListPDFGenerator({
  data,
  year,
  week,
  dayName,
  filename,
  buttonText,
  pillKey,
  amountAccessor,
  t,
}: ArticleAmountTickListPDFGeneratorProps) {
  return (
    <ListPDFGenerator
      data={data}
      filename={filename}
      buttonText={buttonText}
      documentLoader={() => import("./ArticleAmountTickListPDF")}
      // ``data ?? []`` coerces the wrapper-input nullable shape into the
      // document's required ``T[]``. ListPDFGenerator disables the button when
      // ``data`` is null/undefined, so the loader never fires with empty data
      // at runtime — the coercion just satisfies the type system.
      documentProps={{
        data: data ?? [],
        year,
        week,
        dayName,
        pillKey,
        amountAccessor,
        t,
      }}
    />
  );
}
