import { Document, Page, StyleSheet, Text, View } from "@react-pdf/renderer";
import type { TFunction } from "i18next";
import { listStyles } from "./listPdfBase";
import {
  ListPDFFooter,
  ListPDFHeader,
  TickBox,
} from "./ListPDFSharedComponents";

// ─── Article-amount tick-list styles ───────────────────────────────────────
//
// Shared "article · amount · note · ✓" list used by the washing and cleaning
// worksheets — the same document parameterized by which processing-amount text
// it prints (wash vs clean) and its category pill.

const styles = StyleSheet.create({
  colArticle: {
    width: "38%",
  },
  colAmount: {
    width: "22%",
  },
  colDone: {
    width: "8%",
  },
});

// ─── Types ──────────────────────────────────────────────────────────────────

export interface ArticleAmountTickItem {
  id?: number | string;
  computed_article_with_size?: string;
  note?: string;
  // Variant-specific processing-amount text — one is present per list kind.
  computed_total_clean_amount_text?: string;
  computed_total_wash_amount_text?: string;
}

export interface ArticleAmountTickListPDFProps {
  data: ArticleAmountTickItem[];
  year: number;
  week: number;
  dayName: string;
  /** Category pill key — cleaning vs washing list. */
  pillKey: string;
  /** Reads the per-item amount text to print (clean vs wash total). */
  amountAccessor: (item: ArticleAmountTickItem) => string | undefined;
  t: TFunction;
}

// ─── Variant configuration (reused by the thin public wrappers) ─────────────

export const CLEANING_LIST_PILL_KEY = "commissioning.cleaning_list";
export const WASHING_LIST_PILL_KEY = "commissioning.washing_list";

export const cleanAmountAccessor = (item: ArticleAmountTickItem) =>
  item.computed_total_clean_amount_text;
export const washAmountAccessor = (item: ArticleAmountTickItem) =>
  item.computed_total_wash_amount_text;

// ─── Component ──────────────────────────────────────────────────────────────

const ArticleAmountTickListPDF = ({
  data,
  year: _year,
  week,
  dayName,
  pillKey,
  amountAccessor,
  t,
}: ArticleAmountTickListPDFProps) => {
  return (
    <Document>
      <Page size="A4" style={listStyles.page}>
        <ListPDFHeader pill={t(pillKey)}>
          <Text style={listStyles.title}>
            {t("commissioning.KW")} {week} · {dayName}
          </Text>
        </ListPDFHeader>

        <View style={listStyles.table}>
          {/* Table Header */}
          <View style={listStyles.tableHeader} fixed>
            <View style={[listStyles.cell, styles.colArticle, listStyles.cellLeft]}>
              <Text>{t("commissioning.vegetables_and_fruits")}</Text>
            </View>
            <View style={[listStyles.cell, styles.colAmount, listStyles.cellCenter]}>
              <Text>{t("commissioning.amount")}</Text>
            </View>
            <View style={[listStyles.cell, listStyles.colNote, listStyles.cellLeft]}>
              <Text>{t("commissioning.note")}</Text>
            </View>
            <View style={[listStyles.cell, styles.colDone, listStyles.cellCenter]}>
              <Text>{"✓"}</Text>
            </View>
          </View>

          {/* Table Rows */}
          {data.map((item, index) => (
            <View
              key={item.id ?? index}
              style={listStyles.tableRow}
              wrap={false}
            >
              <View style={[listStyles.cell, styles.colArticle, listStyles.cellLeft]}>
                <Text style={{ fontWeight: 500 }}>{item.computed_article_with_size || ""}</Text>
              </View>
              <View style={[listStyles.cell, styles.colAmount, listStyles.cellCenter]}>
                <Text style={{ fontWeight: 700 }}>{amountAccessor(item) || ""}</Text>
              </View>
              <View style={[listStyles.cell, listStyles.colNote, listStyles.cellLeft]}>
                <Text>{item.note || ""}</Text>
              </View>
              <View style={[listStyles.cell, styles.colDone, listStyles.cellCenter]}>
                <TickBox />
              </View>
            </View>
          ))}
        </View>

        <ListPDFFooter t={t} />
      </Page>
    </Document>
  );
};

export default ArticleAmountTickListPDF;
