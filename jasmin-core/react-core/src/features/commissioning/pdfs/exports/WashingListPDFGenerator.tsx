import type { TFunction } from "i18next";
import type { WashingListPDFProps } from "./WashingListPDF";
import ArticleAmountTickListPDFGenerator from "./ArticleAmountTickListPDFGenerator";
import { washAmountAccessor } from "./ArticleAmountTickListPDF";

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
      pillKey="commissioning.washing_list"
      amountAccessor={washAmountAccessor}
    />
  );
}
