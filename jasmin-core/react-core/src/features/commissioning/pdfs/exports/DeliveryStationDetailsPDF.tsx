import { Document, Page, StyleSheet, Text, View } from "@react-pdf/renderer";
import type { TFunction } from "i18next";

import type { PackingBoxesMatrixColumn } from "@shared/api/generated/models";

import {
  ComboHeader,
  boxComboStyles,
  comboColumnWidth,
  computeGroupEdges,
  groupComboColumns,
  pickComboOrientation,
  type PdfOrientation,
} from "./boxComboPdf";
import { listStyles } from "./listPdfBase";
import {
  ListPDFFooter,
  ListPDFHeader,
  TickBox,
  type TenantInfo as SharedTenantInfo,
} from "./ListPDFSharedComponents";
import {
  PackingBoxesMatrixPage,
  type PackingBoxesMatrixItem,
} from "./PackingBoxesMatrixPDF";

// Fixed pt widths; the leading member-name column is fixed so the combos
// follow right after it.
const TICK_WIDTH = 34;
const NAME_MIN_WIDTH = 140;

const localStyles = StyleSheet.create({
  tickCol: {
    width: TICK_WIDTH,
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
  // Optional "Was ihr nehmen könnt" member per-share matrix for THIS station,
  // rendered as a follow-up page right after the station's pickup list so the
  // office prints both together. Omitted (or empty) ⇒ no extra page.
  memberColumns?: PackingBoxesMatrixColumn[];
  memberRows?: PackingBoxesMatrixItem[];
  // Whether the member matrix shows the size column (tenant setting).
  showSize?: boolean;
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
  orientation,
  week,
  dayName,
  tenant,
  t,
}: {
  stationName: string;
  columns: PackingBoxesMatrixColumn[];
  rows: MemberRow[];
  orientation: PdfOrientation;
  week: number;
  dayName: string;
  tenant: TenantInfo;
  t: TFunction;
}) {
  // Group combination columns by base share_type for the parent header row.
  const groups = groupComboColumns(columns, t);
  const groupEdges = computeGroupEdges(groups);
  // Green rules framing each base-share_type group: left on its first column,
  // right on its last.
  const edgeBorders = (key: string) => [
    groupEdges.get(key)?.left ? boxComboStyles.groupBorderLeft : {},
    groupEdges.get(key)?.right ? boxComboStyles.groupBorderRight : {},
  ];

  const comboWidth = comboColumnWidth({
    orientation,
    comboCount: columns.length,
    fixedWidth: TICK_WIDTH,
    flexMinWidth: NAME_MIN_WIDTH,
  });
  // Fixed (not flex) so the combination columns follow immediately instead of
  // being pushed to the right edge; any slack stays on the right.
  const nameCell = { width: NAME_MIN_WIDTH };

  return (
    <Page size="A4" orientation={orientation} style={listStyles.page}>
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
        {/* Group header row: each base share_type short_name spans its combos,
            framed by the green group rules on both sides. */}
        <View
          style={[listStyles.tableHeaderShaded, { borderBottomWidth: 0.5 }]}
          fixed
        >
          <View style={[listStyles.cell, nameCell, listStyles.cellLeft]}>
            <Text> </Text>
          </View>
          {groups.map((group) => (
            <View
              key={group.id}
              style={[
                listStyles.cell,
                { width: comboWidth * group.cols.length },
                listStyles.cellCenter,
                boxComboStyles.groupBorderLeft,
                boxComboStyles.groupBorderRight,
              ]}
            >
              <Text style={boxComboStyles.comboBase}>{group.name}</Text>
            </View>
          ))}
          <View
            style={[listStyles.cell, localStyles.tickCol, listStyles.cellCenter]}
          >
            <Text> </Text>
          </View>
        </View>

        {/* Sub-header row: combination labels + tick column */}
        <View style={listStyles.tableHeaderShaded} fixed>
          <View style={[listStyles.cell, nameCell, listStyles.cellLeft]}>
            <Text>{t("commissioning.pickup_name")}</Text>
          </View>
          {columns.map((column) => (
            <View
              key={column.key}
              style={[
                listStyles.cell,
                { width: comboWidth },
                listStyles.cellCenter,
                ...edgeBorders(column.key),
              ]}
            >
              <ComboHeader column={column} t={t} />
            </View>
          ))}
          <View
            style={[listStyles.cell, localStyles.tickCol, listStyles.cellCenter]}
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
            <View style={[listStyles.cell, nameCell, listStyles.cellLeft]}>
              <Text style={{ fontWeight: 500 }}>{member.name || "-"}</Text>
            </View>
            {columns.map((column) => (
              <View
                key={column.key}
                style={[
                  listStyles.cell,
                  { width: comboWidth },
                  listStyles.cellCenter,
                  ...edgeBorders(column.key),
                ]}
              >
                <Text>{formatCount(member[column.key])}</Text>
              </View>
            ))}
            <View
              style={[listStyles.cell, localStyles.tickCol, listStyles.cellCenter]}
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
  // One orientation for the whole document, chosen from the widest station page.
  const maxComboCount = pages.reduce(
    (max, page) => Math.max(max, page.columns.length),
    0,
  );
  const orientation = pickComboOrientation({
    maxComboCount,
    fixedWidth: TICK_WIDTH,
    flexMinWidth: NAME_MIN_WIDTH,
  });

  return (
    <Document>
      {/* Flat array of <Page>s (Document children must be Pages — no Fragment
          wrapper). Each station contributes its pickup page and, when present,
          its "Was ihr nehmen könnt" member page right after it. */}
      {pages.flatMap((page, idx) => {
        const stationPages = [
          <StationPageContent
            key={`${idx}-pickup`}
            stationName={page.stationName}
            columns={page.columns}
            rows={page.rows}
            orientation={orientation}
            week={week}
            dayName={dayName}
            tenant={tenant}
            t={t}
          />,
        ];
        if (page.memberColumns?.length && page.memberRows?.length) {
          stationPages.push(
            <PackingBoxesMatrixPage
              key={`${idx}-member`}
              columns={page.memberColumns}
              data={page.memberRows}
              week={week}
              dayName={`${page.stationName} · ${dayName}`}
              showSize={page.showSize}
              tenant={tenant}
              pillKey="commissioning.packing_list_bulk_member"
              showCountRow={false}
              t={t}
            />,
          );
        }
        return stationPages;
      })}
    </Document>
  );
}
