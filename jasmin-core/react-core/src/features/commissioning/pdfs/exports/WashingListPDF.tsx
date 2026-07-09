import type { TFunction } from "i18next";
import ArticleAmountTickListPDF, {
  WASHING_LIST_PILL_KEY,
  washAmountAccessor,
  type ArticleAmountTickItem,
} from "./ArticleAmountTickListPDF";

// The washing worksheet is the shared ``ArticleAmountTickListPDF`` pinned to the
// washing variant (pill + ``computed_total_wash_amount_text``). Kept as a public
// entry point so callers importing the document directly stay stable.

export interface WashingListPDFProps {
  data: ArticleAmountTickItem[];
  year: number;
  week: number;
  dayName: string;
  t: TFunction;
}

const WashingListPDF = (props: WashingListPDFProps) => (
  <ArticleAmountTickListPDF
    {...props}
    pillKey={WASHING_LIST_PILL_KEY}
    amountAccessor={washAmountAccessor}
  />
);

export default WashingListPDF;
