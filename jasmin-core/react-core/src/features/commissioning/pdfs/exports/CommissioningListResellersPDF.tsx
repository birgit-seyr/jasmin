import { Document, Page, StyleSheet, Text, View } from "@react-pdf/renderer";
import type { TFunction } from "i18next";
import type { CommissioningListEntry } from "@shared/api/generated/models";
import { useVegetableSizeOptions, useUnitOptions } from "@hooks/index";
import { formatNumber } from "@shared/utils/numberFormat";
import { listStyles } from "./listPdfBase";
import {
  ListPDFFooter,
  ListPDFHeader,
  TickBox,
} from "./ListPDFSharedComponents";
import { pdfTheme } from "./pdfTheme";

const localStyles = StyleSheet.create({
  resellerSection: {
    marginBottom: 16,
  },
  table: {
    width: "100%",
  },
  // ``tableHeaderPadding`` used to be a complete tableHeader style
  // duplicating ``listStyles.tableHeader``. Now we just override the
  // single extra rule (``padding: 5``) and compose at render time
  // via ``style={[listStyles.tableHeader, localStyles.tableHeaderPadding]}``.
  tableHeaderPadding: {
    padding: 5,
  },
  colAmount: {
    width: "22%",
  },
  colVegetable: {
    width: "28%",
  },
  colAmountPerPu: {
    width: "15%",
    fontSize: 9,
  },
  colDone: {
    width: "6%",
  },
});

export interface CommissioningListResellersPDFProps {
  data: CommissioningListEntry[];
  year: number;
  week: number;
  dayName: string;
  t: TFunction;
  /** BCP-47 number locale (e.g. "de-DE"). Passed in because the PDF is
   *  rendered outside the React tree where `useNumberFormat` is unavailable. */
  locale?: string;
}

function TableHeader({ t }: { t: TFunction }) {
  return (
    <View
      style={[listStyles.tableHeader, localStyles.tableHeaderPadding]}
      fixed
    >
      <View
        style={[listStyles.cell, localStyles.colAmount, listStyles.cellLeft]}
      >
        <Text>{t("commissioning.amount")}</Text>
      </View>
      <View
        style={[listStyles.cell, localStyles.colVegetable, listStyles.cellLeft]}
      >
        <Text>{t("commissioning.vegetable")}</Text>
      </View>
      <View
        style={[
          listStyles.cell,
          localStyles.colAmountPerPu,
          listStyles.cellRight,
        ]}
      >
        <Text>{t("commissioning.per_pu")}</Text>
      </View>
      <View style={[listStyles.cell, listStyles.colNote, listStyles.cellLeft]}>
        <Text>{t("commissioning.note")}</Text>
      </View>
      <View
        style={[listStyles.cell, localStyles.colDone, listStyles.cellCenter]}
      >
        <Text>{"✓"}</Text>
      </View>
    </View>
  );
}

const CommissioningListResellersPDF = ({
  data,
  week,
  dayName,
  t,
  locale = "de-DE",
}: CommissioningListResellersPDFProps) => {
  const { getUnitLabel } = useUnitOptions();
  const { getVegetableSizeLabel } = useVegetableSizeOptions();

  const resellersWithOrders = data.filter(
    (reseller) =>
      reseller.order?.contents?.length && reseller.order.contents.length > 0,
  );

  return (
    <Document>
      <Page size="A4" style={listStyles.page}>
        <ListPDFHeader
          pill={t("commissioning.commissioning_list_resellers_short")}
        >
          <Text style={listStyles.title}>
            {t("commissioning.KW")} {week} · {dayName}
          </Text>
        </ListPDFHeader>

        {resellersWithOrders.map((reseller) => (
          <View key={reseller.id} style={localStyles.resellerSection}>
            <View style={listStyles.sectionHeading}>
              <Text>{reseller.name}</Text>
            </View>

            <View style={localStyles.table}>
              <TableHeader t={t} />

              {reseller.order!.contents.map((item, index) => {
                const amount = Number(item.amount);
                const amountPerPu = Number(item.amount_per_pu);
                const puCount =
                  !isNaN(amount) && !isNaN(amountPerPu) && amountPerPu !== 0
                    ? formatNumber(amount / amountPerPu, 1, locale)
                    : "-";
                const formattedAmount = !isNaN(amount)
                  ? formatNumber(amount, 1, locale)
                  : "-";
                const isLast = index === reseller.order!.contents.length - 1;

                return (
                  <View
                    key={item.share_article_id ?? index}
                    style={[
                      listStyles.tableRow,
                      isLast ? listStyles.tableRowLast : {},
                    ]}
                    wrap={false}
                  >
                    <View
                      style={[
                        listStyles.cell,
                        localStyles.colAmount,
                        listStyles.cellLeft,
                      ]}
                    >
                      <Text style={{ fontWeight: 700 }}>
                        {puCount} {t("commissioning.pu")} ({formattedAmount}{" "}
                        {getUnitLabel(item.unit ?? "") || ""})
                      </Text>
                    </View>
                    <View
                      style={[
                        listStyles.cell,
                        localStyles.colVegetable,
                        listStyles.cellLeft,
                      ]}
                    >
                      <Text style={{ fontWeight: 500 }}>
                        {item.share_article_name}
                        {item.size &&
                          item.size !== "M" &&
                          `, ${getVegetableSizeLabel(item.size)}`}
                      </Text>
                    </View>
                    <View
                      style={[
                        listStyles.cell,
                        localStyles.colAmountPerPu,
                        listStyles.cellRight,
                      ]}
                    >
                      <Text style={{ color: pdfTheme.colors.text.secondary }}>
                        ({formatNumber(item.amount_per_pu, 2, locale)}{" "}
                        {getUnitLabel(item.unit ?? "") || ""}/
                        {t("commissioning.pu")})
                      </Text>
                    </View>
                    <View
                      style={[
                        listStyles.cell,
                        listStyles.colNote,
                        listStyles.cellLeft,
                      ]}
                    >
                      <Text>{item.note || ""}</Text>
                    </View>
                    <View
                      style={[
                        listStyles.cell,
                        localStyles.colDone,
                        listStyles.cellCenter,
                      ]}
                    >
                      <TickBox />
                    </View>
                  </View>
                );
              })}
            </View>
          </View>
        ))}

        <ListPDFFooter t={t} />
      </Page>
    </Document>
  );
};

export default CommissioningListResellersPDF;
