import type { TFunction } from "i18next";
import ArticleAmountTickListPDF, {
  cleanAmountAccessor,
  type ArticleAmountTickItem,
} from "./ArticleAmountTickListPDF";

// The cleaning worksheet is the shared ``ArticleAmountTickListPDF`` pinned to
// the cleaning variant (pill + ``computed_total_clean_amount_text``). Kept as a
// public entry point so callers importing the document directly stay stable.

export interface CleaningListPDFProps {
  data: ArticleAmountTickItem[];
  year: number;
  week: number;
  dayName: string;
  t: TFunction;
}

const CleaningListPDF = (props: CleaningListPDFProps) => (
  <ArticleAmountTickListPDF
    {...props}
    pillKey="commissioning.cleaning_list"
    amountAccessor={cleanAmountAccessor}
  />
);

export default CleaningListPDF;
