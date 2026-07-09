import { Document, Page, StyleSheet, Text, View } from "@react-pdf/renderer";
import type { TFunction } from "i18next";

import type { PackingBoxesMatrixColumn } from "@shared/api/generated/models";

import {
  ComboColumnHeaderRow,
  ComboGroupHeaderRow,
  comboColumnWidth,
  computeGroupEdges,
  formatComboCount,
  groupComboColumns,
  groupEdgeStyles,
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

export interface PackingBoxesMatrixItem {
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
  /** Header pill/category label. Defaults to the packing-boxes label; the
   *  member "Was ihr nehmen könnt" variant passes its own. */
  pillKey?: string;
  /** Render the trailing per-combination count row. On for the packing boxes
   *  matrix (box count); off for the member per-share list (no box count). */
  showCountRow?: boolean;
  t: TFunction;
}

/**
 * The matrix as a single ``<Page>`` (no ``<Document>`` wrapper) so it can be
 * embedded into another document — e.g. appended after each station's pickup
 * page in the delivery-station-details PDF. Computes its own orientation from
 * its column count, so it can sit next to differently-oriented pages.
 */
export const PackingBoxesMatrixPage = ({
  columns,
  data,
  week,
  dayName,
  showSize = true,
  tenant,
  pillKey = "commissioning.packing_list_boxes",
  showCountRow = true,
  t,
}: PackingBoxesMatrixPDFProps) => {
  const groups = groupComboColumns(columns, t);
  // Per-column-key: is it the FIRST (green left line) and/or LAST (green right
  // line) column of its base share_type group?
  const groupEdge = computeGroupEdges(groups);
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
    <Page size="A4" orientation={orientation} style={listStyles.page}>
      <ListPDFHeader tenant={tenant} pill={t(pillKey)}>
          <Text style={listStyles.title}>
            {t("commissioning.KW")} {week} · {dayName}
          </Text>
        </ListPDFHeader>

        <View style={listStyles.table}>
          {/* Parent header: each base share_type name spans its combinations */}
          <ComboGroupHeaderRow
            groups={groups}
            comboWidth={comboWidth}
            leading={
              <>
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
              </>
            }
            trailing={
              <>
                <View style={[listStyles.cell, localStyles.colNote]}>
                  <Text></Text>
                </View>
                <View style={[listStyles.cell, localStyles.colDone]}>
                  <Text></Text>
                </View>
              </>
            }
          />

          {/* Column headers */}
          <ComboColumnHeaderRow
            columns={columns}
            comboWidth={comboWidth}
            groupEdges={groupEdge}
            t={t}
            leading={
              <>
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
                ></View>
                {showSize && (
                  <View
                    style={[
                      listStyles.cell,
                      localStyles.colSize,
                      listStyles.cellCenter,
                    ]}
                  ></View>
                )}
              </>
            }
            trailing={
              <>
                <View
                  style={[
                    listStyles.cell,
                    localStyles.colNote,
                    listStyles.cellLeft,
                  ]}
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
              </>
            }
          />

          {/* Article rows */}
          {data.map((item, index) => (
            <View
              key={item.id || index}
              style={listStyles.tableRow}
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
                    ...groupEdgeStyles(groupEdge, column.key),
                  ]}
                >
                  <Text>{formatComboCount(item[column.key])}</Text>
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

          {/* Box-count row (per combination in the current scope) — last row.
              Hidden on the member per-share list, which has no box count. */}
          {showCountRow && (
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
                  ...groupEdgeStyles(groupEdge, column.key),
                ]}
              >
                <Text>{column.count || ""}</Text>
              </View>
            ))}
            <View
              style={[
                listStyles.cell,
                localStyles.colNote,
                listStyles.cellLeft,
              ]}
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
          )}
        </View>

        <ListPDFFooter t={t} />
      </Page>
  );
};

const PackingBoxesMatrixPDF = (props: PackingBoxesMatrixPDFProps) => (
  <Document>
    <PackingBoxesMatrixPage {...props} />
  </Document>
);

export default PackingBoxesMatrixPDF;
