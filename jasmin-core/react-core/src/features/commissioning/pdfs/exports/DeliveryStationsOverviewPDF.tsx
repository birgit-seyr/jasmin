import { Document, Page, Text, View } from "@react-pdf/renderer";
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
import { ListPDFFooter, ListPDFHeader } from "./ListPDFSharedComponents";

// Fixed width for the leading station-name column; the combos follow right
// after it at a fixed pt width.
const NAME_MIN_WIDTH = 120;

// A minimal, strict subset of the generated ``StationOverview`` (the name
// fields are ``allow_null`` on the backend serializer). No index signature —
// keeping it a subset lets a ``StationOverview[]`` assign straight in; the
// dynamic per-combination ``combo_<key>`` counts are read with a local cast.
interface StationRow {
  delivery_station_day_id?: string;
  delivery_station_short_name?: string | null;
  delivery_station_name?: string | null;
}

interface TourPageData {
  tour_number: number;
  // Each tour carries its OWN box-combination columns (they differ per tour).
  columns: PackingBoxesMatrixColumn[];
  stations: StationRow[];
}

export interface DeliveryStationsOverviewPDFProps {
  tours: TourPageData[];
  week: number;
  dayName: string;
  t: TFunction;
}

function formatCount(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return "";
  return String(n);
}

function TourPageContent({
  tour_number,
  stations,
  columns,
  orientation,
  week,
  dayName,
  t,
}: {
  tour_number: number;
  stations: StationRow[];
  columns: PackingBoxesMatrixColumn[];
  orientation: PdfOrientation;
  week: number;
  dayName: string;
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
    fixedWidth: 0,
    flexMinWidth: NAME_MIN_WIDTH,
  });
  // Fixed (not flex) so the combination columns sit right after it instead of
  // being pushed to the right edge; any slack stays on the right.
  const nameCell = { width: NAME_MIN_WIDTH };

  return (
    <Page size="A4" orientation={orientation} style={listStyles.page}>
      <ListPDFHeader pill={t("commissioning.deliveries_overview")}>
        <Text style={listStyles.title}>
          {t("commissioning.KW")} {week} · {dayName} ·{" "}
          {t("commissioning.tour_number", { number: tour_number })}
        </Text>
      </ListPDFHeader>

      <View style={listStyles.table}>
        {/* Parent header: each base share_type short_name spans its combos,
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
        </View>

        {/* Sub-header: combination labels (base size + add-on badges) */}
        <View style={listStyles.tableHeaderShaded} fixed>
          <View style={[listStyles.cell, nameCell, listStyles.cellLeft]}>
            <Text>{t("commissioning.delivery_station")}</Text>
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
        </View>

        {/* Data rows: one per station, cells = box count of that combination */}
        {stations.map((station, index) => (
          <View
            key={(station.delivery_station_day_id as string) || index}
            style={[
              listStyles.tableRow,
              index % 2 === 1 ? listStyles.tableRowAlt : {},
            ]}
            wrap={false}
          >
            <View style={[listStyles.cell, nameCell, listStyles.cellLeft]}>
              <Text style={{ fontWeight: 500 }}>
                {station.delivery_station_short_name ||
                  station.delivery_station_name ||
                  "-"}
              </Text>
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
                <Text>
                  {formatCount(
                    (station as Record<string, unknown>)[column.key],
                  )}
                </Text>
              </View>
            ))}
          </View>
        ))}
      </View>

      <ListPDFFooter t={t} />
    </Page>
  );
}

export default function DeliveryStationsOverviewPDF({
  tours,
  week,
  dayName,
  t,
}: DeliveryStationsOverviewPDFProps) {
  // One orientation for the whole document, chosen from the widest tour.
  const maxComboCount = tours.reduce(
    (max, tour) => Math.max(max, tour.columns.length),
    0,
  );
  const orientation = pickComboOrientation({
    maxComboCount,
    fixedWidth: 0,
    flexMinWidth: NAME_MIN_WIDTH,
  });

  return (
    <Document>
      {tours.map((tour) => (
        <TourPageContent
          key={tour.tour_number}
          tour_number={tour.tour_number}
          stations={tour.stations}
          columns={tour.columns}
          orientation={orientation}
          week={week}
          dayName={dayName}
          t={t}
        />
      ))}
    </Document>
  );
}
