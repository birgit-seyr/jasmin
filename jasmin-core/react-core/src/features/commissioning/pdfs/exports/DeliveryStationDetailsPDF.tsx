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
  type TenantInfo as SharedTenantInfo,
} from "./ListPDFSharedComponents";
import { pdfTheme } from "./pdfTheme";

const PRIMARY_COLOR = pdfTheme.colors.brand;

const localStyles = StyleSheet.create({
  tickCol: {
    width: "8%",
  },
});

interface VariationMeta {
  id: string;
  size: string;
  share_type: string;
  share_type_name: string;
}

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
  members: MemberRow[];
}

export interface DeliveryStationDetailsPDFProps {
  pages: StationPageData[];
  week: number;
  dayName: string;
  variations: VariationMeta[];
  tenant: TenantInfo;
  t: TFunction;
}

function StationPageContent({
  stationName,
  members,
  week,
  dayName,
  variations,
  tenant,
  t,
}: {
  stationName: string;
  members: MemberRow[];
  week: number;
  dayName: string;
  variations: VariationMeta[];
  tenant: TenantInfo;
  t: TFunction;
}) {
  // Group variations by share_type for two-level header
  const groups: { name: string; variations: VariationMeta[] }[] = [];
  const seen: Record<string, number> = {};
  variations.forEach((v) => {
    if (!(v.share_type in seen)) {
      seen[v.share_type] = groups.length;
      groups.push({ name: v.share_type_name, variations: [] });
    }
    groups[seen[v.share_type]].variations.push(v);
  });
  const orderedVariations = groups.flatMap((g) => g.variations);
  const groupStartIds = new Set(groups.map((g) => g.variations[0].id));

  const nameWidth = 30;
  const tickWidth = 8;
  const variationsWidth = 100 - nameWidth - tickWidth;
  const colWidth =
    orderedVariations.length > 0
      ? variationsWidth / orderedVariations.length
      : 8;

  const groupBorder = { borderLeftWidth: 1.5, borderLeftColor: PRIMARY_COLOR };

  return (
    <Page size="A4" style={listStyles.page}>
      {/*
        Branded header — same shared ``ListPDFHeader`` the packing list
        member-facing variant uses, so the pickup list and the
        packing list look like they came from the same office. Title
        + sub-info go through as children; the brand strip (logo + name
        + contact) is rendered above by the shared component when
        ``tenant`` is provided. Previous layout was a 3-column row
        (logo / identity / title-right-aligned) with a heavier 2pt
        border; the new layout stacks the brand strip above a
        left-aligned title block.
      */}
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
        {/* Group header row (share type names) */}
        <View
          style={[listStyles.tableHeader, { borderBottomWidth: 0.5 }]}
          fixed
        >
          <View
            style={[
              listStyles.cell,
              { width: `${nameWidth}%` },
              listStyles.cellLeft,
            ]}
          >
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
          <View
            style={[
              listStyles.cell,
              localStyles.tickCol,
              listStyles.cellCenter,
            ]}
          >
            <Text> </Text>
          </View>
        </View>

        {/* Sub-header row (variation sizes + tick column) */}
        <View style={[listStyles.tableHeader]} fixed>
          <View
            style={[
              listStyles.cell,
              { width: `${nameWidth}%` },
              listStyles.cellLeft,
            ]}
          >
            <Text>{t("commissioning.pickup_name")}</Text>
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

        {/* Data rows */}
        {members.map((member, index) => (
          <View
            key={member.id || index}
            style={[
              listStyles.tableRow,
              index % 2 === 1 ? listStyles.tableRowAlt : {},
            ]}
            wrap={false}
          >
            <View
              style={[
                listStyles.cell,
                { width: `${nameWidth}%` },
                listStyles.cellLeft,
              ]}
            >
              <Text style={{ fontWeight: 500 }}>{member.name || "-"}</Text>
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
                <Text>{(member[`variation_${v.id}`] as number) || ""}</Text>
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
  variations,
  tenant,
  t,
}: DeliveryStationDetailsPDFProps) {
  return (
    <Document>
      {pages.map((page, idx) => (
        <StationPageContent
          key={idx}
          stationName={page.stationName}
          members={page.members}
          week={week}
          dayName={dayName}
          variations={variations}
          tenant={tenant}
          t={t}
        />
      ))}
    </Document>
  );
}
