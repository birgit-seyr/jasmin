import {
  Document,
  Page,
  StyleSheet,
  Text,
  View,
} from "@react-pdf/renderer";
import type { TFunction } from "i18next";
import { listStyles } from "./listPdfBase";
import {
  ListPDFFooter,
  ListPDFHeader,
  TickBox,
} from "./ListPDFSharedComponents";

const localStyles = StyleSheet.create({
  colArticle: {
    width: "40%",
  },
  colSize: {
    width: "12%",
  },
  // Holds amount + unit together (like the washing list).
  colAmount: {
    width: "18%",
  },
  colDone: {
    width: "8%",
  },
});

export interface PackingListBulkItem {
  id?: string | number;
  share_article_name?: string;
  unit_label?: string;
  size_label?: string;
  total_amount?: number;
  note?: string;
}

export interface PackingListBulkPDFProps {
  data: PackingListBulkItem[];
  year: number;
  week: number | null;
  dayName: string;
  shareType?: string;
  deliveryStationName?: string;
  /** Hide the size column when the tenant's ``show_size_column`` is off. */
  showSize?: boolean;
  t: TFunction;
}

const PackingListBulkPDF = ({
  data,
  week,
  dayName,
  shareType,
  deliveryStationName,
  showSize = true,
  t,
}: PackingListBulkPDFProps) => {
  return (
    <Document>
      <Page size="A4" style={listStyles.page}>
        <ListPDFHeader pill={t("commissioning.packing_list_bulk")}>
          <Text style={listStyles.title}>
            {t("commissioning.KW")} {week} · {dayName}
          </Text>
          {shareType && (
            <Text style={listStyles.subtitle}>{shareType}</Text>
          )}
          {deliveryStationName && (
            <Text style={listStyles.subtitle}>{deliveryStationName}</Text>
          )}
        </ListPDFHeader>

        <View style={listStyles.table}>
          <View style={listStyles.tableHeader} fixed>
            <View style={[listStyles.cell, localStyles.colArticle, listStyles.cellLeft]}>
              <Text>{t("commissioning.vegetables_and_fruits")}</Text>
            </View>
            {showSize && (
              <View style={[listStyles.cell, localStyles.colSize, listStyles.cellCenter]}>
                <Text>{t("commissioning.size")}</Text>
              </View>
            )}
            <View style={[listStyles.cell, localStyles.colAmount, listStyles.cellCenter]}>
              <Text>{t("commissioning.total_amount")}</Text>
            </View>
            <View style={[listStyles.cell, listStyles.colNote, listStyles.cellLeft]}>
              <Text>{t("commissioning.note")}</Text>
            </View>
            <View style={[listStyles.cell, localStyles.colDone, listStyles.cellCenter]}>
              <Text>{"✓"}</Text>
            </View>
          </View>

          {data.map((item, index) => (
            <View
              key={item.id || index}
              style={[listStyles.tableRow, index % 2 === 1 ? listStyles.tableRowAlt : {}]}
              wrap={false}
            >
              <View style={[listStyles.cell, localStyles.colArticle, listStyles.cellLeft]}>
                <Text>{item.share_article_name || ""}</Text>
              </View>
              {showSize && (
                <View style={[listStyles.cell, localStyles.colSize, listStyles.cellCenter]}>
                  <Text>{item.size_label || ""}</Text>
                </View>
              )}
              <View style={[listStyles.cell, localStyles.colAmount, listStyles.cellCenter]}>
                <Text>
                  {item.total_amount != null
                    ? `${item.total_amount} ${item.unit_label ?? ""}`.trim()
                    : ""}
                </Text>
              </View>
              <View style={[listStyles.cell, listStyles.colNote, listStyles.cellLeft]}>
                <Text>{item.note || ""}</Text>
              </View>
              <View style={[listStyles.cell, localStyles.colDone, listStyles.cellCenter]}>
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

export default PackingListBulkPDF;
