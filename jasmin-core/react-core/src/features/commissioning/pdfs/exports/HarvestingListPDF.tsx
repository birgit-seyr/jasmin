import { Text, View } from "@react-pdf/renderer";
import { useTranslation } from "react-i18next";
import { baseStyles } from "./baseStyles";
import BaseListPDF from "./BaseListPDF";
import {
  VariationsTotalsCard,
  type VariationTotal,
} from "./ListPDFSharedComponents";

interface CrateData {
  crate_name?: string;
  quantity?: number;
}

interface FirstPageOnlyTableProps {
  dataFirstPageOnly: CrateData[];
  t: (key: string) => string;
  styles: typeof baseStyles;
}

const FirstPageOnlyTable = ({
  dataFirstPageOnly,
  t,
  styles,
}: FirstPageOnlyTableProps) => {
  if (!dataFirstPageOnly || dataFirstPageOnly.length === 0) return null;

  return (
    <View style={{ marginBottom: 24 }}>
      <View style={[styles.table, { width: "100%" }]}>
        <View style={styles.tableRow}>
          <View style={[styles.tableColHeader, { width: "70%" }]}>
            <Text style={styles.tableCellHeaderLeft}>
              {t("commissioning.harvesting_crate")}
            </Text>
          </View>
          <View
            style={[
              styles.tableColHeader,
              styles.tableColHeaderLast,
              { width: "30%" },
            ]}
          >
            <Text style={styles.tableCellHeaderCenter}>
              {t("commissioning.quantity")}
            </Text>
          </View>
        </View>
        {dataFirstPageOnly.map((crate, index) => (
          <View style={styles.tableRow} key={index}>
            <View style={[styles.tableCol, { width: "70%" }]}>
              <Text style={[styles.tableCell, styles.tableCellLeft]}>
                {crate.crate_name || "—"}
              </Text>
            </View>
            <View
              style={[styles.tableCol, styles.tableColLast, { width: "30%" }]}
            >
              <Text style={[styles.tableCell, styles.tableCellAmount]}>
                {crate.quantity || 0}
              </Text>
            </View>
          </View>
        ))}
      </View>
    </View>
  );
};

interface HarvestingListPDFProps {
  data: Record<string, unknown>[];
  dataFirstPageOnly?: CrateData[];
  variationsTotals?: VariationTotal[];
  title: string;
  subtitle: string;
  pill?: string;
  columns: unknown[];
}

const HarvestingListPDF = ({
  data,
  dataFirstPageOnly,
  variationsTotals,
  title,
  subtitle,
  pill,
  columns,
}: HarvestingListPDFProps) => {
  const { t } = useTranslation();

  // Variation totals next to the harvesting-crate totals (side by side).
  const firstPageContent = (
    <View style={{ flexDirection: "row", gap: 16, alignItems: "flex-start" }}>
      <View style={{ width: "48%" }}>
        <VariationsTotalsCard variationsTotals={variationsTotals} t={t} />
      </View>
      <View style={{ width: "48%" }}>
        <FirstPageOnlyTable
          dataFirstPageOnly={dataFirstPageOnly || []}
          t={t}
          styles={baseStyles}
        />
      </View>
    </View>
  );

  return (
    <BaseListPDF
      title={title}
      subtitle={subtitle}
      pill={pill}
      data={data}
      firstPageContent={firstPageContent}
      columns={columns}
      orientation="landscape"
    />
  );
};

export default HarvestingListPDF;
