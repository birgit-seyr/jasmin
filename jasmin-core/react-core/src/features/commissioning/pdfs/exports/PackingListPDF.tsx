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
  VariationsTotalsCard,
  type TenantInfo,
  type VariationTotal,
} from "./ListPDFSharedComponents";

const localStyles = StyleSheet.create({
  subtitleStrong: {
    fontSize: 11,
    color: "#666",
    marginBottom: 3,
    fontWeight: 700,
    textAlign: "left",
  },
  colArticle: {
    width: "30%",
  },
  colUnit: {
    width: "10%",
  },
  colSize: {
    width: "10%",
  },
  colVariation: {
    width: "10%",
  },
  colDone: {
    width: "6%",
  },
});

interface Variation {
  id?: string;
  size: string;
}

interface PackingItem {
  id?: string | number;
  share_article_name?: string;
  unit_label?: string;
  size_label?: string;
  note?: string;
  [key: string]: unknown;
}

export interface PackingListPDFProps {
  data: PackingItem[];
  year: number;
  week: number | null;
  dayName: string;
  shareType?: string;
  variations: Variation[];
  variationsTotals?: VariationTotal[];
  packingStation?: string | number | null;
  // i18n key for the document title. Defaults to the staff boxes label;
  // member-facing variants (e.g. self-pack in MIXED/BULK mode) override it.
  titleKey?: string;
  // Optional — when provided, the brand strip (logo + tenant name) is
  // rendered above the title block. Useful for member-facing variants
  // where the recipient is outside the office and the source needs to
  // be unambiguous.
  tenant?: TenantInfo;
  /** Hide the size column when the tenant's ``show_size_column`` is off. */
  showSize?: boolean;
  t: TFunction;
}

export interface PackingStationPage {
  stationNumber: number;
  data: PackingItem[];
  variationsTotals?: VariationTotal[];
}

export interface PackingListAllStationsPDFProps {
  pages: PackingStationPage[];
  year: number;
  week: number | null;
  dayName: string;
  shareType?: string;
  variations: Variation[];
  tenant?: TenantInfo;
  showSize?: boolean;
  t: TFunction;
}

function PackingListPageContent({
  data,
  week,
  dayName,
  shareType,
  variations,
  variationsTotals,
  packingStationLabel,
  titleKey,
  tenant,
  showSize,
  t,
}: {
  data: PackingItem[];
  week: number | null;
  dayName: string;
  shareType?: string;
  variations: Variation[];
  variationsTotals?: VariationTotal[];
  packingStationLabel?: string;
  titleKey?: string;
  tenant?: TenantInfo;
  showSize: boolean;
  t: TFunction;
}) {
  return (
    <Page size="A4" style={listStyles.page}>
      <ListPDFHeader
        tenant={tenant}
        pill={t(titleKey ?? "commissioning.packing_list_boxes")}
      >
        <Text style={listStyles.title}>
          {t("commissioning.KW")} {week} · {dayName}
        </Text>
        <Text style={listStyles.subtitle}>{shareType && `${shareType}`}</Text>
        {packingStationLabel && (
          <Text style={localStyles.subtitleStrong}>{packingStationLabel}</Text>
        )}
      </ListPDFHeader>

      <VariationsTotalsCard variationsTotals={variationsTotals} t={t} />

      <View style={listStyles.table}>
        <View style={listStyles.tableHeader} fixed>
          <View style={[listStyles.cell, localStyles.colArticle, listStyles.cellLeft]}>
            <Text>{t("commissioning.vegetables_and_fruits")}</Text>
          </View>
          <View style={[listStyles.cell, localStyles.colUnit, listStyles.cellCenter]}>
            <Text>{t("commissioning.unit")}</Text>
          </View>
          {showSize && (
            <View style={[listStyles.cell, localStyles.colSize, listStyles.cellCenter]}>
              <Text>{t("commissioning.size")}</Text>
            </View>
          )}
          {variations.map((variation, index) => (
            <View
              key={variation.id || index}
              style={[listStyles.cell, localStyles.colVariation, listStyles.cellCenter]}
            >
              <Text>{t(`commissioning.${variation.size}`)}</Text>
            </View>
          ))}
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
            <View style={[listStyles.cell, localStyles.colUnit, listStyles.cellCenter]}>
              <Text>{item.unit_label || ""}</Text>
            </View>
            {showSize && (
              <View style={[listStyles.cell, localStyles.colSize, listStyles.cellCenter]}>
                <Text>{item.size_label || ""}</Text>
              </View>
            )}
            {variations.map((variation, idx) => (
              <View
                key={variation.id || idx}
                style={[listStyles.cell, localStyles.colVariation, listStyles.cellCenter]}
              >
                <Text>
                  {(item[`variation_${variation.id}`] as string) || ""}
                </Text>
              </View>
            ))}
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
  );
}

const PackingListPDF = ({
  data,
  week,
  dayName,
  shareType,
  variations,
  variationsTotals,
  packingStation,
  titleKey,
  tenant,
  showSize = true,
  t,
}: PackingListPDFProps) => {
  return (
    <Document>
      <PackingListPageContent
        data={data}
        week={week}
        dayName={dayName}
        shareType={shareType}
        variations={variations}
        variationsTotals={variationsTotals}
        packingStationLabel={
          packingStation
            ? t("commissioning.packing_station_number", {
                number: packingStation,
              })
            : undefined
        }
        titleKey={titleKey}
        tenant={tenant}
        showSize={showSize}
        t={t}
      />
    </Document>
  );
};

export const PackingListAllStationsPDF = ({
  pages,
  week,
  dayName,
  shareType,
  variations,
  tenant,
  showSize = true,
  t,
}: PackingListAllStationsPDFProps) => {
  const totalStations = pages.length;

  return (
    <Document>
      {pages.map((page, index) => (
        <PackingListPageContent
          key={page.stationNumber}
          data={page.data}
          week={week}
          dayName={dayName}
          shareType={shareType}
          variations={variations}
          variationsTotals={page.variationsTotals}
          packingStationLabel={t("commissioning.packing_station_x_of_y", {
            current: index + 1,
            total: totalStations,
          })}
          tenant={tenant}
          showSize={showSize}
          t={t}
        />
      ))}
    </Document>
  );
};

export default PackingListPDF;
