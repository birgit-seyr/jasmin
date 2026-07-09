import type { TFunction } from "i18next";
import type { WashingListPDFProps } from "./WashingListPDF";
import ArticleAmountTickListPDFGenerator from "./ArticleAmountTickListPDFGenerator";
import {
  WASHING_LIST_PILL_KEY,
  washAmountAccessor,
} from "./ArticleAmountTickListPDF";

interface WashingListPDFGeneratorProps {
  data: WashingListPDFProps["data"] | null;
  year: number;
  week: number;
  dayName: string;
  filename: string;
  buttonText: string;
  t: TFunction;
}

export default function WashingListPDFGenerator(
  props: WashingListPDFGeneratorProps,
) {
  return (
    <ArticleAmountTickListPDFGenerator
      {...props}
      pillKey={WASHING_LIST_PILL_KEY}
      amountAccessor={washAmountAccessor}
    />
  );
}
