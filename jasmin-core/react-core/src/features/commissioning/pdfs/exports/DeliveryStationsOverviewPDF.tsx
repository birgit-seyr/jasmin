import { Document, Page, Text, View, StyleSheet } from "@react-pdf/renderer";
import type { TFunction } from "i18next";
import { listStyles } from "./listPdfBase";
import { ListPDFFooter, ListPDFHeader } from "./ListPDFSharedComponents";
import { pdfTheme } from "./pdfTheme";

const PRIMARY_COLOR = pdfTheme.colors.brand;

interface VariationMeta {
  id: string;
  size: string;
  share_type: string;
  share_type_name: string;
}

// A minimal, strict subset of the generated ``StationOverview`` (the name
// fields are ``allow_null`` on the backend serializer). No index signature —
// keeping it a subset lets a ``StationOverview[]`` assign straight in; the
// dynamic per-variation ``variation_<id>`` counts are read with a local cast.
interface StationRow {
  delivery_station_day_id?: string;
  delivery_station_short_name?: string | null;
  delivery_station_name?: string | null;
}

interface TourPageData {
  tour_number: number;
  stations: StationRow[];
}

export interface DeliveryStationsOverviewPDFProps {
  tours: TourPageData[];
  week: number;
  dayName: string;
  variations: VariationMeta[];
  t: TFunction;
}

function TourPageContent({
  tour_number,
  stations,
  week,
  dayName,
  variations,
  t,
}: {
  tour_number: number;
  stations: StationRow[];
  week: number;
  dayName: string;
  variations: VariationMeta[];
  t: TFunction;
}) {
  // Group variations by share_type ID for header (matching the table's grouping)
  const groups: { name: string; variations: VariationMeta[] }[] = [];
  const seen: Record<string, number> = {};
  variations.forEach((v) => {
    if (!(v.share_type in seen)) {
      seen[v.share_type] = groups.length;
      groups.push({ name: v.share_type_name, variations: [] });
    }
    groups[seen[v.share_type]].variations.push(v);
  });

  // Flatten groups into the correct order so sub-header & data columns
  // line up with the parent group header columns
  const orderedVariations = groups.flatMap((g) => g.variations);

  // Track which variation IDs start a new share type group (for vertical lines)
  const groupStartIds = new Set(groups.map((g) => g.variations[0].id));

  // Match table proportions: station = 12 units, each variation = 6 units
  const variationCount = orderedVariations.length;
  const stationUnits = 12;
  const variationUnits = 6;
  const totalUnits = stationUnits + variationUnits * variationCount;
  const stationWidth = (stationUnits / totalUnits) * 100;
  const colWidth = (variationUnits / totalUnits) * 100;

  const groupBorder = { borderLeftWidth: 1.5, borderLeftColor: PRIMARY_COLOR };

  return (
    <Page size="A4" style={listStyles.page}>
      <ListPDFHeader pill={t("commissioning.deliveries_overview")}>
        <Text style={listStyles.title}>
          {t("commissioning.KW")} {week} · {dayName} ·{" "}
          {t("commissioning.tour_number", { number: tour_number })}
        </Text>
      </ListPDFHeader>

      <View style={listStyles.table}>
        {/* Two-level header: share type group row */}
        <View style={[listStyles.tableHeader, { borderBottomWidth: 0.5 }]} fixed>
          <View style={[listStyles.cell, { width: `${stationWidth}%` }, listStyles.cellLeft]}>
            <Text> </Text>
          </View>
          {groups.map((group) => (
            <View
              key={group.name}
              style={[
                listStyles.cell,
                { width: `${colWidth * group.variations.length}%` },
                listStyles.cellCenter,
                groupBorder,
              ]}
            >
              <Text style={{ fontWeight: 700 }}>{group.name}</Text>
            </View>
          ))}
        </View>

        {/* Sub-header: variation sizes */}
        <View style={[listStyles.tableHeader]} fixed>
          <View style={[listStyles.cell, { width: `${stationWidth}%` }, listStyles.cellLeft]}>
            <Text>{t("commissioning.delivery_station")}</Text>
          </View>
          {orderedVariations.map((v) => (
            <View
              key={v.id}
              style={[
                listStyles.cell,
                { width: `${colWidth}%` },
                listStyles.cellCenter,
                groupStartIds.has(v.id) ? groupBorder : {},
              ]}
            >
              <Text>{t(`commissioning.${v.size}`)}</Text>
            </View>
          ))}
        </View>

        {/* Data rows */}
        {stations.map((station, index) => (
          <View
            key={(station.delivery_station_day_id as string) || index}
            style={[
              listStyles.tableRow,
              index % 2 === 1 ? listStyles.tableRowAlt : {},
            ]}
            wrap={false}
          >
            <View style={[listStyles.cell, { width: `${stationWidth}%` }, listStyles.cellLeft]}>
              <Text style={{ fontWeight: 500 }}>
                {station.delivery_station_short_name ||
                  station.delivery_station_name ||
                  "-"}
              </Text>
            </View>
            {orderedVariations.map((v) => (
              <View
                key={v.id}
                style={[
                  listStyles.cell,
                  { width: `${colWidth}%` },
                  listStyles.cellCenter,
                  groupStartIds.has(v.id) ? groupBorder : {},
                ]}
              >
                <Text>
                  {((station as Record<string, unknown>)[
                    `variation_${v.id}`
                  ] as number) || 0}
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
  variations,
  t,
}: DeliveryStationsOverviewPDFProps) {
  return (
    <Document>
      {tours.map((tour) => (
        <TourPageContent
          key={tour.tour_number}
          tour_number={tour.tour_number}
          stations={tour.stations}
          week={week}
          dayName={dayName}
          variations={variations}
          t={t}
        />
      ))}
    </Document>
  );
}
