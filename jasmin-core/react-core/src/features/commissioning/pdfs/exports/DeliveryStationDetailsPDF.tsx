import { Document, Page, StyleSheet, Text, View } from "@react-pdf/renderer";
import type { TFunction } from "i18next";

import type { PackingBoxesMatrixColumn } from "@shared/api/generated/models";

import { ComboHeader, boxComboStyles, groupComboColumns } from "./boxComboPdf";
import { listStyles } from "./listPdfBase";
import {
  ListPDFFooter,
  ListPDFHeader,
  TickBox,
  type TenantInfo as SharedTenantInfo,
} from "./ListPDFSharedComponents";
import { pdfTheme } from "./pdfTheme";

const PRIMARY_COLOR = pdfTheme.colors.brand;

const localStyles = StyleSheet.create({
  tickCol: {
    width: "8%",
  },
});

interface MemberRow {
  id?: string;
  name?: string;
  [key: string]: unknown;
}

export interface TenantInfo {
  name?: string;
  logoUrl?: string | null;
  email?: string;
  phone?: string;
}

export interface StationPageData {
  stationName: string;
  // Each station has its OWN box-combination columns (different members ⇒
  // different combinations), so the columns travel with the page, not shared.
  columns: PackingBoxesMatrixColumn[];
  rows: MemberRow[];
}

export interface DeliveryStationDetailsPDFProps {
  pages: StationPageData[];
  week: number;
  dayName: string;
  tenant: TenantInfo;
  t: TFunction;
}

function formatCount(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return "";
  return String(n);
}

function StationPageContent({
  stationName,
  columns,
  rows,
  week,
  dayName,
  tenant,
  t,
}: {
  stationName: string;
  columns: PackingBoxesMatrixColumn[];
  rows: MemberRow[];
  week: number;
  dayName: string;
  tenant: TenantInfo;
  t: TFunction;
}) {
  // Group combination columns by base share_type for the parent header row.
  const groups = groupComboColumns(columns, t);
  const groupStartKeys = new Set(groups.map((group) => group.cols[0]?.key));

  const nameWidth = 30;
  const tickWidth = 8;
  const combosWidth = 100 - nameWidth - tickWidth;
  const colWidth = columns.length > 0 ? combosWidth / columns.length : 8;

  const groupBorder = { borderLeftWidth: 1.5, borderLeftColor: PRIMARY_COLOR };

  return (
    <Page size="A4" style={listStyles.page}>
      <ListPDFHeader
        tenant={tenant as SharedTenantInfo}
        pill={t("commissioning.delivery_notes_delivery_stations_details")}
      >
        <Text style={listStyles.title}>{stationName}</Text>
        <Text style={listStyles.subtitle}>
          {t("commissioning.KW")} {week} · {dayName}
        </Text>
      </ListPDFHeader>

      <View style={listStyles.table}>
        {/* Group header row: each base share_type short_name spans its combos */}
        <View style={[listStyles.tableHeader, { borderBottomWidth: 0.5 }]} fixed>
          <View
            style={[listStyles.cell, { width: `${nameWidth}%` }, listStyles.cellLeft]}
          >
            <Text> </Text>
          </View>
          {groups.map((group) => (
            <View
              key={group.id}
              style={[
                listStyles.cell,
                { width: `${colWidth * group.cols.length}%` },
                listStyles.cellCenter,
                groupBorder,
              ]}
            >
              <Text style={boxComboStyles.comboBase}>{group.name}</Text>
            </View>
          ))}
          <View style={[listStyles.cell, localStyles.tickCol, listStyles.cellCenter]}>
            <Text> </Text>
          </View>
        </View>

        {/* Sub-header row: combination labels + tick column */}
        <View style={[listStyles.tableHeader]} fixed>
          <View
            style={[listStyles.cell, { width: `${nameWidth}%` }, listStyles.cellLeft]}
          >
            <Text>{t("commissioning.pickup_name")}</Text>
          </View>
          {columns.map((column) => (
            <View
              key={column.key}
              style={[
                listStyles.cell,
                { width: `${colWidth}%` },
                listStyles.cellCenter,
                groupStartKeys.has(column.key) ? groupBorder : {},
              ]}
            >
              <ComboHeader column={column} t={t} />
            </View>
          ))}
          <View
            style={[
              listStyles.cell,
              localStyles.tickCol,
              listStyles.cellCenter,
              groupBorder,
            ]}
          >
            <Text>{"✓"}</Text>
          </View>
        </View>

        {/* Data rows: one per member, cells = box count of that combination */}
        {rows.map((member, index) => (
          <View
            key={member.id || index}
            style={[
              listStyles.tableRow,
              index % 2 === 1 ? listStyles.tableRowAlt : {},
            ]}
            wrap={false}
          >
            <View
              style={[listStyles.cell, { width: `${nameWidth}%` }, listStyles.cellLeft]}
            >
              <Text style={{ fontWeight: 500 }}>{member.name || "-"}</Text>
            </View>
            {columns.map((column) => (
              <View
                key={column.key}
                style={[
                  listStyles.cell,
                  { width: `${colWidth}%` },
                  listStyles.cellCenter,
                  groupStartKeys.has(column.key) ? groupBorder : {},
                ]}
              >
                <Text>{formatCount(member[column.key])}</Text>
              </View>
            ))}
            <View
              style={[
                listStyles.cell,
                localStyles.tickCol,
                listStyles.cellCenter,
                groupBorder,
              ]}
            >
              <TickBox />
            </View>
          </View>
        ))}
      </View>

      <ListPDFFooter t={t} />
    </Page>
  );
}

export default function DeliveryStationDetailsPDF({
  pages,
  week,
  dayName,
  tenant,
  t,
}: DeliveryStationDetailsPDFProps) {
  return (
    <Document>
      {pages.map((page, idx) => (
        <StationPageContent
          key={idx}
          stationName={page.stationName}
          columns={page.columns}
          rows={page.rows}
          week={week}
          dayName={dayName}
          tenant={tenant}
          t={t}
        />
      ))}
    </Document>
  );
}
