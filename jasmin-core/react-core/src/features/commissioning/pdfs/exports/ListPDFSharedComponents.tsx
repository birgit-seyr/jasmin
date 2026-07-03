import type { ReactNode } from "react";
import { Image, StyleSheet, Text, View } from "@react-pdf/renderer";
import type { TFunction } from "i18next";
import { listStyles as styles } from "./listPdfBase";
import { pdfTheme } from "./pdfTheme";

// ─── Tenant header info ────────────────────────────────────────────────────
//
// Optional branded strip rendered above the list title — logo on the
// left, tenant name + contact on the right. Mirrors the shape used by
// ``DeliveryStationDetailsPDF.TenantInfo`` so pages that already build
// a ``tenantInfo`` object (e.g. ``DeliveryStationsDetails.tsx``) can
// reuse it across multiple list PDFs without massaging shapes.

export interface TenantInfo {
  name?: string;
  logoUrl?: string | null;
  email?: string;
  phone?: string;
}

const PRIMARY_COLOR = pdfTheme.colors.brand;

const headerStyles = StyleSheet.create({
  // Category chip rendered above the title — a green-outlined pill that
  // names the document type (e.g. "WASCH-LISTE") so the kind of sheet is
  // legible at a glance while the title line carries the context (KW, day).
  pill: {
    alignSelf: "flex-start",
    borderWidth: 1,
    borderColor: PRIMARY_COLOR,
    borderRadius: 3,
    paddingVertical: 2,
    paddingHorizontal: 6,
    marginBottom: 5,
  },
  pillText: {
    fontSize: 8,
    fontWeight: 700,
    color: PRIMARY_COLOR,
    textTransform: "uppercase",
    letterSpacing: 0.8,
  },
  // Empty bordered square for "done"/"✓" columns — something to physically
  // tick on the printed sheet (the old layout left the cell blank).
  tickBox: {
    width: 11,
    height: 11,
    borderWidth: 1,
    borderColor: pdfTheme.colors.border.strong,
    borderRadius: 2,
    alignSelf: "center",
  },
  // Header row: title content on the LEFT, tenant block on the RIGHT.
  // The whole row is rendered inside the existing ``styles.header``
  // wrapper (which carries the section's bottom border + spacing).
  headerRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 12,
  },
  // ``flex: 1`` so the title takes whatever space the tenant block
  // doesn't claim. Wrapper exists to give the children a flex
  // constraint without callers having to know about the layout.
  titleColumn: {
    flex: 1,
  },
  // Right-side tenant block — logo on top, name and contact stacked
  // below it, everything right-aligned so the logo sits in the
  // corner regardless of how short the contact lines are.
  tenantColumn: {
    alignItems: "flex-end",
    maxWidth: 200,
  },
  logo: {
    width: 50,
    height: 50,
    objectFit: "contain",
    marginBottom: 3,
  },
  tenantName: {
    fontSize: 10,
    fontWeight: 700,
    color: PRIMARY_COLOR,
    textAlign: "right",
  },
  tenantContact: {
    fontSize: 8,
    color: "#666",
    textAlign: "right",
  },
});

// NOTE: ``ListPDFGenerator`` used to live in this file. It got moved
// to ./ListPDFGenerator.tsx so the click-to-load button doesn't drag
// ``@react-pdf/renderer`` (eagerly imported in this file for the
// header/footer helpers) into every page's eager bundle. Header and
// footer remain here because they're only used INSIDE PDF document
// components, which are themselves dynamically imported — so their
// transitive @react-pdf dependency never leaks into the eager bundle.

// ─── PDF Footer with page numbers ──────────────────────────────────────────

export function ListPDFFooter({ t }: { t: TFunction }) {
  return (
    <View style={styles.footer} fixed>
      <Text
        style={styles.pageNumber}
        render={({ pageNumber, totalPages }) =>
          `${t("common.page")} ${pageNumber} ${t("common.of")} ${totalPages}`
        }
      />
    </View>
  );
}

// ─── PDF Header with title ──────────────────────────────────────────────────

export function ListPDFHeader({
  children,
  tenant,
  pill,
}: {
  children: ReactNode;
  /**
   * Optional branded strip — when provided, the tenant logo + name +
   * contact render on the RIGHT side of the header, with the title
   * content (``children``) taking the remaining width on the left.
   * Omit on internal-only PDFs where the brand isn't useful (e.g.
   * harvest worksheets). ``styles.header`` keeps its existing
   * spacing + bottom border; this just splits the inside into two
   * columns when tenant info is present.
   */
  tenant?: TenantInfo;
  /**
   * Optional category label rendered as a green-outlined pill above the
   * title (e.g. the translated list name). Lets the title line carry
   * just the context (KW, day, station).
   */
  pill?: string;
}) {
  const hasTenant = !!(tenant && (tenant.logoUrl || tenant.name));
  const titleBlock = (
    <>
      {pill && (
        <View style={headerStyles.pill}>
          <Text style={headerStyles.pillText}>{pill}</Text>
        </View>
      )}
      {children}
    </>
  );
  return (
    <View style={styles.header}>
      {hasTenant ? (
        <View style={headerStyles.headerRow}>
          <View style={headerStyles.titleColumn}>{titleBlock}</View>
          <View style={headerStyles.tenantColumn}>
            {tenant!.logoUrl && (
              <Image src={tenant!.logoUrl} style={headerStyles.logo} />
            )}
            {tenant!.name && (
              <Text style={headerStyles.tenantName}>{tenant!.name}</Text>
            )}
            {tenant!.email && (
              <Text style={headerStyles.tenantContact}>{tenant!.email}</Text>
            )}
            {tenant!.phone && (
              <Text style={headerStyles.tenantContact}>{tenant!.phone}</Text>
            )}
          </View>
        </View>
      ) : (
        titleBlock
      )}
    </View>
  );
}

// ─── Tick box ───────────────────────────────────────────────────────────────

/** Empty bordered square for "done"/"✓" columns — gives staff something to
 *  physically tick on the printed sheet. */
export function TickBox() {
  return <View style={headerStyles.tickBox} />;
}

// ─── Variations totals card ────────────────────────────────────────────────

/** One row in the ``VariationsTotalsCard``. Previously declared
 * independently in HarvestingListPDF and PackingListPDF; consolidated
 * here so the type and the renderer stay in sync. ``id`` accepts
 * ``string | number`` because the upstream ``VariationsTotalEntry``
 * type in the page layer uses numeric ids — used only as a React
 * key in the renderer, where both are valid. */
export interface VariationTotal {
  id?: string | number;
  size: string;
  totalQuantity: number | string;
}

const variationsCardStyles = StyleSheet.create({
  card: {
    marginBottom: 12,
    padding: 8,
    backgroundColor: "#f9f9f9",
    borderRadius: 4,
  },
  title: {
    fontSize: 11,
    fontWeight: 700,
    marginBottom: 5,
  },
  row: {
    flexDirection: "row",
    fontSize: 10,
    marginBottom: 2,
  },
  label: {
    width: 80,
    fontWeight: 500,
  },
  value: {
    fontWeight: 400,
  },
});

/**
 * Grey rounded card listing each variation size and its total quantity.
 * Used as page-1 content on HarvestingListPDF and rendered between
 * header and table on PackingListPDF. Renders ``null`` for empty /
 * undefined input so callers can pass through directly without a
 * length check.
 */
export function VariationsTotalsCard({
  variationsTotals,
  t,
}: {
  variationsTotals: VariationTotal[] | undefined;
  t: TFunction;
}) {
  if (!variationsTotals || variationsTotals.length === 0) return null;
  return (
    <View style={variationsCardStyles.card}>
      <Text style={variationsCardStyles.title}>
        {t("commissioning.variations_totals")}
      </Text>
      {variationsTotals.map((variation, index) => (
        <View key={variation.id || index} style={variationsCardStyles.row}>
          <Text style={variationsCardStyles.label}>
            {t(`commissioning.${variation.size}`)}:
          </Text>
          <Text style={variationsCardStyles.value}>
            {variation.totalQuantity}
          </Text>
        </View>
      ))}
    </View>
  );
}
