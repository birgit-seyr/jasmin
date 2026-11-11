import type { TFunction } from "i18next";
import type { MarketPriceListPDFProps } from "./MarketPriceListPDF";
import ListPDFGenerator from "./ListPDFGenerator";

// ``MarketPriceListPDF`` is NOT statically imported — see ListPDFGenerator's
// docstring. The lazy factory keeps @react-pdf/renderer + the PDF template
// out of the page's eager bundle.

interface MarketPriceListPDFGeneratorProps {
  groups: MarketPriceListPDFProps["groups"] | null;
  /** False while the week's prices are still loading. */
  isReady?: boolean;
  year: number;
  week: number;
  subtitle?: string;
  filename: string;
  buttonText: string;
  t: TFunction;
}

export default function MarketPriceListPDFGenerator({
  groups,
  isReady,
  year,
  week,
  subtitle,
  filename,
  buttonText,
  t,
}: MarketPriceListPDFGeneratorProps) {
  return (
    <ListPDFGenerator
      // An empty array (no active price this week) disables the button.
      data={groups}
      isReady={isReady}
      filename={filename}
      buttonText={buttonText}
      documentLoader={() => import("./MarketPriceListPDF")}
      documentProps={{ groups: groups ?? [], year, week, subtitle, t }}
    />
  );
}
