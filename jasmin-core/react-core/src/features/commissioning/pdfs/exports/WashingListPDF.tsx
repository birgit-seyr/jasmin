import { Document, Page, StyleSheet, Text, View } from "@react-pdf/renderer";
import type { TFunction } from "i18next";
import { listStyles } from "./listPdfBase";
import {
  ListPDFFooter,
  ListPDFHeader,
  TickBox,
} from "./ListPDFSharedComponents";

// ─── Washing-list specific styles ───────────────────────────────────────────

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

interface WashingItem {
  id?: number | string;
  computed_article_with_size?: string;
  computed_total_wash_amount_text?: string;
  note?: string;
}

export interface WashingListPDFProps {
  data: WashingItem[];
  year: number;
  week: number;
  dayName: string;
  t: TFunction;
}

// ─── Component ──────────────────────────────────────────────────────────────

const WashingListPDF = ({ data, year: _year, week, dayName, t }: WashingListPDFProps) => {
  return (
    <Document>
      <Page size="A4" style={listStyles.page}>
        <ListPDFHeader pill={t("commissioning.washing_list")}>
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
              style={[
                listStyles.tableRow,
                index % 2 === 1 ? listStyles.tableRowAlt : {},
              ]}
              wrap={false}
            >
              <View style={[listStyles.cell, styles.colArticle, listStyles.cellLeft]}>
                <Text style={{ fontWeight: 500 }}>{item.computed_article_with_size || ""}</Text>
              </View>
              <View style={[listStyles.cell, styles.colAmount, listStyles.cellCenter]}>
                <Text style={{ fontWeight: 700 }}>{item.computed_total_wash_amount_text || ""}</Text>
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

export default WashingListPDF;
