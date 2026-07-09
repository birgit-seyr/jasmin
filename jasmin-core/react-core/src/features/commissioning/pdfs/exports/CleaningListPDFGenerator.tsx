import type { TFunction } from "i18next";
import type { CleaningListPDFProps } from "./CleaningListPDF";
import ArticleAmountTickListPDFGenerator from "./ArticleAmountTickListPDFGenerator";
import {
  CLEANING_LIST_PILL_KEY,
  cleanAmountAccessor,
} from "./ArticleAmountTickListPDF";

interface CleaningListPDFGeneratorProps {
  data: CleaningListPDFProps["data"] | null;
  year: number;
  week: number;
  dayName: string;
  filename: string;
  buttonText: string;
  t: TFunction;
}

export default function CleaningListPDFGenerator(
  props: CleaningListPDFGeneratorProps,
) {
  return (
    <ArticleAmountTickListPDFGenerator
      {...props}
      pillKey={CLEANING_LIST_PILL_KEY}
      amountAccessor={cleanAmountAccessor}
    />
  );
}
