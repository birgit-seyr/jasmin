import { Document, Page, StyleSheet, Text, View } from "@react-pdf/renderer";
import type { TFunction } from "i18next";
import { listStyles } from "./listPdfBase";
import { ListPDFFooter, ListPDFHeader } from "./ListPDFSharedComponents";

// ─── Market-price-list specific styles ──────────────────────────────────────

const localStyles = StyleSheet.create({
  section: {
    marginBottom: 16,
  },
  colPlu: {
    width: "15%",
  },
  colName: {
    width: "55%",
  },
  colPrice: {
    width: "30%",
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
      <View style={[listStyles.cell, localStyles.colPlu, listStyles.cellLeft]}>
        <Text>{t("commissioning.plu_number")}</Text>
      </View>
      <View style={[listStyles.cell, localStyles.colName, listStyles.cellLeft]}>
        <Text>{t("commissioning.market_label")}</Text>
      </View>
      <View style={[listStyles.cell, localStyles.colPrice, listStyles.cellRight]}>
        <Text>{t("commissioning.gross_price")}</Text>
      </View>
    </View>
  );
}

// ─── Component ──────────────────────────────────────────────────────────────

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

        {groupsWithRows.map((group) => (
          <View key={group.label} style={localStyles.section}>
            <View style={listStyles.sectionHeading}>
              <Text>{group.label}</Text>
            </View>

            <View style={listStyles.table}>
              <TableHeader t={t} />

              {group.rows.map((item, index) => (
                <View
                  key={item.id}
                  style={[
                    listStyles.tableRow,
                    index === group.rows.length - 1
                      ? listStyles.tableRowLast
                      : {},
                  ]}
                  wrap={false}
                >
                  <View
                    style={[listStyles.cell, localStyles.colPlu, listStyles.cellLeft]}
                  >
                    <Text style={{ fontWeight: item.is_changed ? 700 : 400 }}>
                      {item.plu_number}
                    </Text>
                  </View>
                  <View
                    style={[listStyles.cell, localStyles.colName, listStyles.cellLeft]}
                  >
                    <Text style={{ fontWeight: item.is_changed ? 700 : 400 }}>
                      {item.name}
                    </Text>
                  </View>
                  <View
                    style={[listStyles.cell, localStyles.colPrice, listStyles.cellRight]}
                  >
                    <Text style={{ fontWeight: item.is_changed ? 700 : 400 }}>
                      {item.price_text}
                    </Text>
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

export default MarketPriceListPDF;
