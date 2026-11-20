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
  /** The total as the page shows it, in the tenant's number format. */
  total_amount_text?: string;
  note?: string;
}

/** One station's list, starting a page of its own. */
export interface PackingListBulkPage {
  deliveryStationName?: string;
  data: PackingListBulkItem[];
}

export interface PackingListBulkPDFProps {
  pages: PackingListBulkPage[];
  year: number;
  week: number | null;
  dayName: string;
  shareType?: string;
  /** Hide the size column when the tenant's ``show_size_column`` is off. */
  showSize?: boolean;
  t: TFunction;
}

const PackingListBulkTable = ({
  data,
  showSize,
  t,
}: {
  data: PackingListBulkItem[];
  showSize: boolean;
  t: TFunction;
}) => (
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
      <View key={item.id || index} style={listStyles.tableRow} wrap={false}>
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
            {item.total_amount_text
              ? `${item.total_amount_text} ${item.unit_label ?? ""}`.trim()
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
);

const PackingListBulkPDF = ({
  pages,
  week,
  dayName,
  shareType,
  showSize = true,
  t,
}: PackingListBulkPDFProps) => (
  <Document>
    {/* A fixed list, built once per download: the index is a stable key. */}
    {pages.map((page, pageIndex) => (
      <Page key={pageIndex} size="A4" style={listStyles.page}>
        {/* Repeated on every sheet a long list runs onto, so each names its
            station. */}
        <View fixed>
          <ListPDFHeader pill={t("commissioning.packing_list_bulk")}>
            <Text style={listStyles.title}>
              {t("commissioning.KW")} {week} · {dayName}
            </Text>
            {shareType && <Text style={listStyles.subtitle}>{shareType}</Text>}
            {page.deliveryStationName && (
              <Text style={listStyles.subtitle}>{page.deliveryStationName}</Text>
            )}
          </ListPDFHeader>
        </View>

        <PackingListBulkTable data={page.data} showSize={showSize} t={t} />

        <ListPDFFooter t={t} />
      </Page>
    ))}
  </Document>
);

export default PackingListBulkPDF;
