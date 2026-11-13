import type { MarketMemberListPDFProps } from "./MarketMemberListPDF";
import ListPDFGenerator from "./ListPDFGenerator";

// ``MarketMemberListPDF`` is NOT statically imported — see ListPDFGenerator's
// docstring. The lazy factory keeps @react-pdf/renderer + the PDF template
// out of the page's eager bundle.

interface MarketMemberListPDFGeneratorProps {
  /** Fetches the members on click: the page that offers the list doesn't
   *  show them. */
  loadDocumentProps: () => Promise<MarketMemberListPDFProps>;
  filename: string;
  buttonText: string;
}

export default function MarketMemberListPDFGenerator({
  loadDocumentProps,
  filename,
  buttonText,
}: MarketMemberListPDFGeneratorProps) {
  return (
    <ListPDFGenerator
      // Nothing to wait for before the click.
      data={true}
      filename={filename}
      buttonText={buttonText}
      documentLoader={() => import("./MarketMemberListPDF")}
      documentProps={loadDocumentProps}
    />
  );
}
