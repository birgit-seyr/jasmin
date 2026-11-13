import { Document, Page, StyleSheet, Text, View } from "@react-pdf/renderer";
import type { TFunction } from "i18next";
import { listStyles } from "./listPdfBase";
import {
  ListPDFFooter,
  ListPDFHeader,
  TickBox,
} from "./ListPDFSharedComponents";

// ─── Market-member-list specific styles ─────────────────────────────────────

const localStyles = StyleSheet.create({
  colName: {
    width: "38%",
  },
  colNumber: {
    width: "14%",
  },
  colTick: {
    flex: 1,
    alignItems: "center",
  },
});

// ─── Types ──────────────────────────────────────────────────────────────────

export interface MarketMemberListItem {
  id: string;
  /** The last name, or the company's name for a member without one. */
  last_name: string;
  first_name: string;
  member_number: number;
}

export interface MarketMemberListPDFProps {
  /** In the order to print, by last name. */
  members: MarketMemberListItem[];
  /** The day it's printed, formatted in the page. */
  asOf: string;
  t: TFunction;
}

// ─── Header ─────────────────────────────────────────────────────────────────

function TableHeader({ t }: { t: TFunction }) {
  return (
    <View style={listStyles.tableHeader} fixed>
      <View style={[listStyles.compactCell, localStyles.colName]}>
        <Text>{t("members.last_name")}</Text>
      </View>
      <View style={[listStyles.compactCell, localStyles.colName]}>
        <Text>{t("members.first_name")}</Text>
      </View>
      <View style={[listStyles.compactCell, localStyles.colNumber]}>
        <Text>{t("members.member_number")}</Text>
      </View>
      <View style={[listStyles.compactCell, localStyles.colTick]}>
        <Text>{"✓"}</Text>
      </View>
    </View>
  );
}

// ─── Component ──────────────────────────────────────────────────────────────

/** The current members for the market stand, with a box to tick each. */
const MarketMemberListPDF = ({ members, asOf, t }: MarketMemberListPDFProps) => (
  <Document>
    <Page size="A4" style={listStyles.page}>
      <ListPDFHeader pill={t("commissioning.market_member_list")}>
        <Text style={listStyles.title}>
          {t("commissioning.market_member_list_as_of", { date: asOf })}
        </Text>
      </ListPDFHeader>

      <View>
        <TableHeader t={t} />

        {members.map((member) => (
          <View key={member.id} style={listStyles.compactRow} wrap={false}>
            <View style={[listStyles.compactCell, localStyles.colName]}>
              <Text>{member.last_name}</Text>
            </View>
            <View style={[listStyles.compactCell, localStyles.colName]}>
              <Text>{member.first_name}</Text>
            </View>
            <View style={[listStyles.compactCell, localStyles.colNumber]}>
              <Text>{member.member_number}</Text>
            </View>
            <View style={[listStyles.compactCell, localStyles.colTick]}>
              <TickBox />
            </View>
          </View>
        ))}
      </View>

      <ListPDFFooter t={t} />
    </Page>
  </Document>
);

export default MarketMemberListPDF;
