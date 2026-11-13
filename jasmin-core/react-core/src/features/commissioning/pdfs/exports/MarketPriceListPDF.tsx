import { Document, Page, StyleSheet, Text, View } from "@react-pdf/renderer";
import type { TFunction } from "i18next";
import { listStyles } from "./listPdfBase";
import { ListPDFFooter, ListPDFHeader } from "./ListPDFSharedComponents";

// ─── Market-price-list specific styles ──────────────────────────────────────

const localStyles = StyleSheet.create({
  // Narrower than the page, so each price sits close to its name; the
  // longest names still fit on one line.
  table: {
    width: "65%",
  },
  colPlu: {
    width: "12%",
  },
  colName: {
    flex: 1,
  },
  colPrice: {
    width: "24%",
  },
});

// ─── Types ──────────────────────────────────────────────────────────────────

export interface MarketPriceListItem {
  id: string;
  plu_number: number;
  /** The PLU's label and the week's origin. */
  name: string;
  /** Gross price per unit, formatted in the page, e.g. "3,49 €/kg". */
  price_text: string;
  /** Printed in bold: the price or the origin changed since last week. */
  is_changed: boolean;
}

export interface MarketPriceListGroup {
  /** The product group, e.g. "4 Apples"; used as the section heading. */
  label: string;
  rows: MarketPriceListItem[];
}

export interface MarketPriceListPDFProps {
  groups: MarketPriceListGroup[];
  year: number;
  week: number;
  /** What the list was narrowed to, e.g. "Changed prices only · 4 Apples". */
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
      <View
        style={[listStyles.compactCell, localStyles.colPrice, listStyles.cellRight]}
      >
        <Text>{t("commissioning.gross_price")}</Text>
      </View>
    </View>
  );
}

// ─── Component ──────────────────────────────────────────────────────────────

/** One table for every group, the column header repeated on each page and
 *  each group's name as a row of its own, so the list stays a few pages. */
const MarketPriceListPDF = ({
  groups,
  year,
  week,
  subtitle,
  t,
}: MarketPriceListPDFProps) => {
  const groupsWithRows = groups.filter((group) => group.rows.length > 0);

  return (
    <Document>
      <Page size="A4" style={listStyles.page}>
        <ListPDFHeader pill={t("commissioning.market_price_list")}>
          <Text style={listStyles.title}>
            {t("commissioning.KW")} {week}/{year}
          </Text>
          {subtitle ? <Text style={listStyles.subtitle}>{subtitle}</Text> : null}
        </ListPDFHeader>

        <View style={localStyles.table}>
          <TableHeader t={t} />

          {groupsWithRows.map((group) => (
            <View key={group.label}>
              <Text style={listStyles.compactGroupHeading} minPresenceAhead={30}>
                {group.label}
              </Text>

              {group.rows.map((item) => {
                const weight = { fontWeight: item.is_changed ? 700 : 400 };
                return (
                  <View key={item.id} style={listStyles.compactRow} wrap={false}>
                    <View style={[listStyles.compactCell, localStyles.colPlu]}>
                      <Text style={weight}>{item.plu_number}</Text>
                    </View>
                    <View style={[listStyles.compactCell, localStyles.colName]}>
                      <Text style={weight}>{item.name}</Text>
                    </View>
                    <View
                      style={[
                        listStyles.compactCell,
                        localStyles.colPrice,
                        listStyles.cellRight,
                      ]}
                    >
                      <Text style={weight}>{item.price_text}</Text>
                    </View>
                  </View>
                );
              })}
            </View>
          ))}
        </View>

        <ListPDFFooter t={t} />
      </Page>
    </Document>
  );
};

export default MarketPriceListPDF;
