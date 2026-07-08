import { Document, Page, StyleSheet, Text, View } from "@react-pdf/renderer";
import type { TFunction } from "i18next";

import type { PackingBoxesMatrixColumn } from "@shared/api/generated/models";

import {
  ComboHeader,
  boxComboStyles,
  comboColumnWidth,
  groupComboColumns,
  pickComboOrientation,
} from "./boxComboPdf";
import { listStyles } from "./listPdfBase";
import {
  ListPDFFooter,
  ListPDFHeader,
  TickBox,
  type TenantInfo,
} from "./ListPDFSharedComponents";

// Fixed pt column widths; the NOTE column flexes to absorb slack, and the
// combination columns take a dynamic pt width (see comboColumnWidth).
const ARTICLE_WIDTH = 130;
const UNIT_WIDTH = 42;
const SIZE_WIDTH = 38;
const DONE_WIDTH = 30;
const NOTE_MIN_WIDTH = 55;

const localStyles = StyleSheet.create({
  colArticle: { width: ARTICLE_WIDTH },
  colUnit: { width: UNIT_WIDTH },
  colSize: { width: SIZE_WIDTH },
  colDone: { width: DONE_WIDTH },
  colNote: { flex: 1, minWidth: NOTE_MIN_WIDTH },
  countRow: { backgroundColor: "#eef2f7", fontWeight: 700 },
  countLabel: { fontWeight: 700 },
});

interface PackingBoxesMatrixItem {
  id?: string | number;
  share_article_name?: string;
  unit_label?: string;
  size_label?: string;
  note?: string;
  [key: string]: unknown;
}

export interface PackingBoxesMatrixPDFProps {
  columns: PackingBoxesMatrixColumn[];
  data: PackingBoxesMatrixItem[];
  week: number | null;
  dayName: string;
  /** Hide the size column when the tenant's ``show_size_column`` is off. */
  showSize?: boolean;
  /** Optional brand strip (logo + tenant name) above the title. */
  tenant?: TenantInfo;
  t: TFunction;
}

function formatAmount(value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return "";
  return String(n);
}

const PackingBoxesMatrixPDF = ({
  columns,
  data,
  week,
  dayName,
  showSize = true,
  tenant,
  t,
}: PackingBoxesMatrixPDFProps) => {
  const groups = groupComboColumns(columns, t);
  const fixedWidth =
    ARTICLE_WIDTH + UNIT_WIDTH + (showSize ? SIZE_WIDTH : 0) + DONE_WIDTH;
  const orientation = pickComboOrientation({
    maxComboCount: columns.length,
    fixedWidth,
    flexMinWidth: NOTE_MIN_WIDTH,
  });
  const comboWidth = comboColumnWidth({
    orientation,
    comboCount: columns.length,
    fixedWidth,
    flexMinWidth: NOTE_MIN_WIDTH,
  });
  return (
    <Document>
      <Page size="A4" orientation={orientation} style={listStyles.page}>
        <ListPDFHeader
          tenant={tenant}
          pill={t("commissioning.packing_list_boxes_2")}
        >
          <Text style={listStyles.title}>
            {t("commissioning.KW")} {week} · {dayName}
          </Text>
        </ListPDFHeader>

        <View style={listStyles.table}>
          {/* Parent header: each base share_type name spans its combinations */}
          <View style={listStyles.tableHeader} fixed>
            <View style={[listStyles.cell, localStyles.colArticle]}>
              <Text></Text>
            </View>
            <View style={[listStyles.cell, localStyles.colUnit]}>
              <Text></Text>
            </View>
            {showSize && (
              <View style={[listStyles.cell, localStyles.colSize]}>
                <Text></Text>
              </View>
            )}
            {groups.map((group) => (
              <View
                key={group.id}
                style={[
                  listStyles.cell,
                  listStyles.cellCenter,
                  { width: comboWidth * group.cols.length },
                ]}
              >
                <Text style={boxComboStyles.comboBase}>{group.name}</Text>
              </View>
            ))}
            <View style={[listStyles.cell, localStyles.colNote]}>
              <Text></Text>
            </View>
            <View style={[listStyles.cell, localStyles.colDone]}>
              <Text></Text>
            </View>
          </View>

          {/* Column headers */}
          <View style={listStyles.tableHeader} fixed>
            <View
              style={[
                listStyles.cell,
                localStyles.colArticle,
                listStyles.cellLeft,
              ]}
            >
              <Text>{t("commissioning.vegetables_and_fruits")}</Text>
            </View>
            <View
              style={[
                listStyles.cell,
                localStyles.colUnit,
                listStyles.cellCenter,
              ]}
            >
              <Text>{t("commissioning.unit")}</Text>
            </View>
            {showSize && (
              <View
                style={[
                  listStyles.cell,
                  localStyles.colSize,
                  listStyles.cellCenter,
                ]}
              >
                <Text>{t("commissioning.size")}</Text>
              </View>
            )}
            {columns.map((column) => (
              <View
                key={column.key}
                style={[
                  listStyles.cell,
                  { width: comboWidth },
                  listStyles.cellCenter,
                ]}
              >
                <ComboHeader column={column} t={t} />
              </View>
            ))}
            <View
              style={[listStyles.cell, localStyles.colNote, listStyles.cellLeft]}
            >
              <Text></Text>
            </View>
            <View
              style={[
                listStyles.cell,
                localStyles.colDone,
                listStyles.cellCenter,
              ]}
            >
              <Text>{"✓"}</Text>
            </View>
          </View>

          {/* Article rows */}
          {data.map((item, index) => (
            <View
              key={item.id || index}
              style={[
                listStyles.tableRow,
                index % 2 === 1 ? listStyles.tableRowAlt : {},
              ]}
              wrap={false}
            >
              <View
                style={[
                  listStyles.cell,
                  localStyles.colArticle,
                  listStyles.cellLeft,
                ]}
              >
                <Text>{item.share_article_name || ""}</Text>
              </View>
              <View
                style={[
                  listStyles.cell,
                  localStyles.colUnit,
                  listStyles.cellCenter,
                ]}
              >
                <Text>{item.unit_label || ""}</Text>
              </View>
              {showSize && (
                <View
                  style={[
                    listStyles.cell,
                    localStyles.colSize,
                    listStyles.cellCenter,
                  ]}
                >
                  <Text>{item.size_label || ""}</Text>
                </View>
              )}
              {columns.map((column) => (
                <View
                  key={column.key}
                  style={[
                    listStyles.cell,
                    { width: comboWidth },
                    listStyles.cellCenter,
                  ]}
                >
                  <Text>{formatAmount(item[column.key])}</Text>
                </View>
              ))}
              <View
                style={[
                  listStyles.cell,
                  localStyles.colNote,
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
          ))}

          {/* Box-count row (per combination in the current scope) — last row */}
          <View
            style={[listStyles.tableRow, localStyles.countRow]}
            wrap={false}
          >
            <View
              style={[
                listStyles.cell,
                localStyles.colArticle,
                listStyles.cellLeft,
              ]}
            >
              <Text style={localStyles.countLabel}>
                {t("commissioning.box_count")}
              </Text>
            </View>
            <View
              style={[
                listStyles.cell,
                localStyles.colUnit,
                listStyles.cellCenter,
              ]}
            >
              <Text></Text>
            </View>
            {showSize && (
              <View
                style={[
                  listStyles.cell,
                  localStyles.colSize,
                  listStyles.cellCenter,
                ]}
              >
                <Text></Text>
              </View>
            )}
            {columns.map((column) => (
              <View
                key={column.key}
                style={[
                  listStyles.cell,
                  { width: comboWidth },
                  listStyles.cellCenter,
                ]}
              >
                <Text>{column.count || ""}</Text>
              </View>
            ))}
            <View
              style={[listStyles.cell, localStyles.colNote, listStyles.cellLeft]}
            >
              <Text></Text>
            </View>
            <View
              style={[
                listStyles.cell,
                localStyles.colDone,
                listStyles.cellCenter,
              ]}
            >
              <Text></Text>
            </View>
          </View>
        </View>

        <ListPDFFooter t={t} />
      </Page>
    </Document>
  );
};

export default PackingBoxesMatrixPDF;
