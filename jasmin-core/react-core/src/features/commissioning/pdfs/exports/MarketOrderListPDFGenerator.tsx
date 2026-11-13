import type { TFunction } from "i18next";
import type { MarketOrderListPDFProps } from "./MarketOrderListPDF";
import ListPDFGenerator from "./ListPDFGenerator";

// ``MarketOrderListPDF`` is NOT statically imported — see ListPDFGenerator's
// docstring. The lazy factory keeps @react-pdf/renderer + the PDF template
// out of the page's eager bundle.

interface MarketOrderListPDFGeneratorProps {
  groups: MarketOrderListPDFProps["groups"] | null;
  /** False while the PLUs or the week's prices are still loading. */
  isReady?: boolean;
  year: number;
  week: number;
  subtitle?: string;
  filename: string;
  buttonText: string;
  t: TFunction;
}

export default function MarketOrderListPDFGenerator({
  groups,
  isReady,
  year,
  week,
  subtitle,
  filename,
  buttonText,
  t,
}: MarketOrderListPDFGeneratorProps) {
  return (
    <ListPDFGenerator
      // An empty array (no active PLU) disables the button.
      data={groups}
      isReady={isReady}
      filename={filename}
      buttonText={buttonText}
      documentLoader={() => import("./MarketOrderListPDF")}
      documentProps={{ groups: groups ?? [], year, week, subtitle, t }}
    />
  );
}
