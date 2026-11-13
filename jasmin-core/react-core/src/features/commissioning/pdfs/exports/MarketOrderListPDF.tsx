import { Document, Page, StyleSheet, Text, View } from "@react-pdf/renderer";
import type { TFunction } from "i18next";
import { listStyles } from "./listPdfBase";
import { ListPDFFooter, ListPDFHeader } from "./ListPDFSharedComponents";
import { pdfTheme } from "./pdfTheme";

// ─── Market-order-list specific styles ──────────────────────────────────────

const localStyles = StyleSheet.create({
  // Room to write the stock and the order by hand.
  row: {
    minHeight: 16,
  },
  colPlu: {
    width: "9%",
  },
  colName: {
    flex: 1,
  },
  colUnit: {
    width: "9%",
  },
  colPrice: {
    width: "12%",
  },
  colWriteIn: {
    width: "15%",
    borderLeftWidth: 0.5,
    borderLeftColor: pdfTheme.colors.border.light,
  },
});

// ─── Types ──────────────────────────────────────────────────────────────────

export interface MarketOrderListItem {
  id: string;
  plu_number: number;
  /** The PLU's label and the week's origin. */
  name: string;
  unit_label: string;
  /** The week's gross price, formatted in the page; empty without one. */
  price_text: string;
}

export interface MarketOrderListGroup {
  /** The product group, e.g. "4 Apples"; used as the section heading. */
  label: string;
  rows: MarketOrderListItem[];
}

export interface MarketOrderListPDFProps {
  groups: MarketOrderListGroup[];
  year: number;
  week: number;
  /** The product groups the list was narrowed to. */
  subtitle?: string;
  t: TFunction;
}

// ─── Header ─────────────────────────────────────────────────────────────────

function TableHeader({ t }: { t: TFunction }) {
  return (
    <View style={listStyles.tableHeader} fixed>
      <View style={[listStyles.compactCell, localStyles.colPlu]}>
        <Text>{t("commissioning.plu_number")}</Text>
      </View>
      <View style={[listStyles.compactCell, localStyles.colName]}>
        <Text>{t("commissioning.market_label")}</Text>
      </View>
      <View style={[listStyles.compactCell, localStyles.colUnit]}>
        <Text>{t("commissioning.unit")}</Text>
      </View>
      <View
        style={[listStyles.compactCell, localStyles.colPrice, listStyles.cellRight]}
      >
        <Text>{t("commissioning.gross_price")}</Text>
      </View>
      <View style={[listStyles.compactCell, localStyles.colWriteIn]}>
        <Text>{t("commissioning.in_stock")}</Text>
      </View>
      <View style={[listStyles.compactCell, localStyles.colWriteIn]}>
        <Text>{t("commissioning.order_amount")}</Text>
      </View>
    </View>
  );
}

// ─── Component ──────────────────────────────────────────────────────────────

/** The market's order form for a week: every PLU by product group with the
 *  week's price, and blank columns for the stock counted and the amount to
 *  order. */
const MarketOrderListPDF = ({
  groups,
  year,
  week,
  subtitle,
  t,
}: MarketOrderListPDFProps) => {
  const groupsWithRows = groups.filter((group) => group.rows.length > 0);

  return (
    <Document>
      <Page size="A4" style={listStyles.page}>
        <ListPDFHeader pill={t("commissioning.market_order_list")}>
          <Text style={listStyles.title}>
            {t("commissioning.KW")} {week}/{year}
          </Text>
          {subtitle ? <Text style={listStyles.subtitle}>{subtitle}</Text> : null}
        </ListPDFHeader>

        <View>
          <TableHeader t={t} />

          {groupsWithRows.map((group) => (
            <View key={group.label}>
              <Text style={listStyles.compactGroupHeading} minPresenceAhead={30}>
                {group.label}
              </Text>

              {group.rows.map((item) => (
                <View
                  key={item.id}
                  style={[listStyles.compactRow, localStyles.row]}
                  wrap={false}
                >
                  <View style={[listStyles.compactCell, localStyles.colPlu]}>
                    <Text>{item.plu_number}</Text>
                  </View>
                  <View style={[listStyles.compactCell, localStyles.colName]}>
                    <Text>{item.name}</Text>
                  </View>
                  <View style={[listStyles.compactCell, localStyles.colUnit]}>
                    <Text>{item.unit_label}</Text>
                  </View>
                  <View
                    style={[
                      listStyles.compactCell,
                      localStyles.colPrice,
                      listStyles.cellRight,
                    ]}
                  >
                    <Text>{item.price_text}</Text>
                  </View>
                  <View style={[listStyles.compactCell, localStyles.colWriteIn]} />
                  <View style={[listStyles.compactCell, localStyles.colWriteIn]} />
                </View>
              ))}
            </View>
          ))}
        </View>

        <ListPDFFooter t={t} />
      </Page>
    </Document>
  );
};

export default MarketOrderListPDF;
