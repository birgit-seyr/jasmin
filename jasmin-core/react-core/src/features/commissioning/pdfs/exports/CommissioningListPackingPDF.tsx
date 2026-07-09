import { Document, Page, StyleSheet, Text, View } from "@react-pdf/renderer";
import type { TFunction } from "i18next";
import { listStyles } from "./listPdfBase";
import {
  ListPDFFooter,
  ListPDFHeader,
  TickBox,
} from "./ListPDFSharedComponents";

// ─── Packing-commissioning-list specific styles ─────────────────────────────

const localStyles = StyleSheet.create({
  section: {
    marginBottom: 16,
  },
  colArticle: {
    width: "45%",
  },
  // Used when the size column is hidden — the article absorbs its width so
  // the row still fills 100%.
  colArticleWide: {
    width: "60%",
  },
  colSize: {
    width: "15%",
  },
  // Holds amount + unit together (like the washing list).
  colAmount: {
    width: "32%",
  },
  colDone: {
    width: "8%",
  },
});

// ─── Types ──────────────────────────────────────────────────────────────────

export interface PackingListItem {
  id?: string;
  share_article_name?: string;
  // Unit / size are resolved to display labels in the page (where the
  // option hooks are available) and passed in as plain strings, so the PDF
  // never calls hooks outside the React tree.
  unit_label?: string;
  size_label?: string;
  total_amount_text?: string;
}

export interface PackingListGroup {
  /** Share-option label (e.g. "Gemüse"); used as the section heading. */
  label: string;
  rows: PackingListItem[];
}

export interface CommissioningListPackingPDFProps {
  groups: PackingListGroup[];
  year: number;
  week: number | null;
  /** Hide the size column when the tenant's ``show_size_column`` is off. */
  showSize?: boolean;
  t: TFunction;
}

// ─── Header ─────────────────────────────────────────────────────────────────

function TableHeader({ t, showSize }: { t: TFunction; showSize: boolean }) {
  return (
    <View style={listStyles.tableHeader} fixed>
      <View
        style={[
          listStyles.cell,
          showSize ? localStyles.colArticle : localStyles.colArticleWide,
          listStyles.cellLeft,
        ]}
      >
        <Text>{t("commissioning.vegetables_and_fruits")}</Text>
      </View>
      {showSize && (
        <View style={[listStyles.cell, localStyles.colSize, listStyles.cellCenter]}>
          <Text>{t("commissioning.size")}</Text>
        </View>
      )}
      <View style={[listStyles.cell, localStyles.colAmount, listStyles.cellRight]}>
        <Text>{t("commissioning.total_amount")}</Text>
      </View>
      <View style={[listStyles.cell, localStyles.colDone, listStyles.cellCenter]}>
        <Text>{"✓"}</Text>
      </View>
    </View>
  );
}

// ─── Component ──────────────────────────────────────────────────────────────

const CommissioningListPackingPDF = ({
  groups,
  year,
  week,
  showSize = true,
  t,
}: CommissioningListPackingPDFProps) => {
  const groupsWithRows = groups.filter((group) => group.rows.length > 0);

  return (
    <Document>
      <Page size="A4" style={listStyles.page}>
        <ListPDFHeader pill={t("commissioning.commissioning_list_packing")}>
          <Text style={listStyles.title}>
            {t("commissioning.KW")} {week}/{year}
          </Text>
        </ListPDFHeader>

        {groupsWithRows.map((group) => (
          <View key={group.label} style={localStyles.section}>
            {groupsWithRows.length > 1 && (
              <View style={listStyles.sectionHeading}>
                <Text>{group.label}</Text>
              </View>
            )}

            <View style={listStyles.table}>
              <TableHeader t={t} showSize={showSize} />

              {group.rows.map((item, index) => (
                <View
                  key={item.id || index}
                  style={[
                    listStyles.tableRow,
                    index === group.rows.length - 1
                      ? listStyles.tableRowLast
                      : {},
                  ]}
                  wrap={false}
                >
                  <View
                    style={[
                      listStyles.cell,
                      showSize
                        ? localStyles.colArticle
                        : localStyles.colArticleWide,
                      listStyles.cellLeft,
                    ]}
                  >
                    <Text style={{ fontWeight: 500 }}>
                      {item.share_article_name || ""}
                    </Text>
                  </View>
                  {showSize && (
                    <View style={[listStyles.cell, localStyles.colSize, listStyles.cellCenter]}>
                      <Text>{item.size_label || ""}</Text>
                    </View>
                  )}
                  <View style={[listStyles.cell, localStyles.colAmount, listStyles.cellRight]}>
                    <Text style={{ fontWeight: 700 }}>
                      {[item.total_amount_text, item.unit_label]
                        .filter(Boolean)
                        .join(" ")}
                    </Text>
                  </View>
                  <View style={[listStyles.cell, localStyles.colDone, listStyles.cellCenter]}>
                    <TickBox />
                  </View>
                </View>
              ))}
            </View>
          </View>
        ))}

        <ListPDFFooter t={t} />
      </Page>
    </Document>
  );
};

export default CommissioningListPackingPDF;
