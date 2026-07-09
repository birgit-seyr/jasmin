import { StyleSheet } from "@react-pdf/renderer";
import { pdfTheme } from "./pdfTheme";
import "../registerRoboto";

const { colors, fontSizes, spacing } = pdfTheme;

/**
 * Shared styles for the simpler list-style PDFs: CleaningListPDF,
 * WashingListPDF, CommissioningListPDF, PackingListPDF,
 * PackingListBulkPDF, DeliveryStationsOverviewPDF,
 * DeliveryStationDetailsPDF. Sibling stylesheet: ``./baseStyles.ts``
 * holds the table primitives for the column-driven ``BaseListPDF``
 * (Harvest / Purchase). Both derive from ``./pdfTheme.ts`` for
 * color/font/spacing tokens.
 *
 * Visual language: "Clean Hairline". No outer table box and no
 * vertical gridlines — the table reads as rows separated by hairline
 * dividers under a single brand-green header rule. Column labels are
 * tiny, uppercase, letter-spaced and muted. The one accent is the
 * brand green (header rule + category pill). This prints cleanly on
 * B/W laser printers and keeps toner use low.
 */
// Header-row primitives shared by ``tableHeader`` (plain hairline) and
// ``tableHeaderShaded`` (the box-combination matrices' slight-grey fill) — one
// definition so the two never drift.
const headerRow = {
  flexDirection: "row",
  borderBottomWidth: 1,
  borderBottomColor: colors.border.default,
  color: colors.text.muted,
  textTransform: "uppercase",
  letterSpacing: 0.6,
  fontWeight: 700,
  fontSize: fontSizes.smaller,
} as const;

export const listStyles = StyleSheet.create({
  page: {
    fontFamily: "Roboto",
    fontSize: fontSizes.small,
    paddingTop: spacing.pageTop,
    paddingBottom: spacing.pageTop,
    paddingHorizontal: spacing.page,
    backgroundColor: colors.page,
    color: colors.text.primary,
  },
  header: {
    marginBottom: spacing.xl,
    borderBottomWidth: 1.5,
    borderBottomColor: colors.brand,
    paddingBottom: spacing.md,
  },
  title: {
    fontSize: 15,
    fontWeight: 700,
    marginBottom: spacing.xxs,
    color: colors.text.primary,
  },
  subtitle: {
    fontSize: fontSizes.small,
    color: colors.text.muted,
    marginBottom: spacing.xxs,
  },
  table: {
    width: "100%",
    marginTop: spacing.lg,
  },
  // No background fill and no surrounding box — just a hairline under
  // the header. Labels inherit the uppercase/letter-spaced/muted text
  // styling from this row (react-pdf cascades text props through the
  // cell Views to their <Text>).
  tableHeader: { ...headerRow },
  // Slight-grey header fill for the box-combination matrices (packing boxes,
  // delivery overview / details); the plain hairline header stays the default
  // elsewhere.
  tableHeaderShaded: { ...headerRow, backgroundColor: colors.tableHeader },
  tableRow: {
    flexDirection: "row",
    borderBottomWidth: 0.5,
    borderBottomColor: colors.border.light,
    minHeight: 30,
  },
  // Zebra striping was intentionally dropped for the Clean Hairline
  // design. Kept as a no-op so the per-list ``index % 2 ? tableRowAlt
  // : {}`` call sites stay valid; the ternaries can be removed when a
  // file is next touched.
  tableRowAlt: {},
  tableRowLast: {
    borderBottomWidth: 0,
  },
  cell: {
    paddingVertical: spacing.sm,
    paddingHorizontal: 5,
    fontSize: fontSizes.small,
    justifyContent: "center",
  },
  cellLeft: {
    textAlign: "left",
  },
  cellCenter: {
    textAlign: "center",
  },
  cellRight: {
    textAlign: "right",
  },
  colNote: {
    flex: 1,
  },
  footer: {
    position: "absolute",
    bottom: 30,
    left: spacing.page,
    right: spacing.page,
    textAlign: "center",
    fontSize: fontSizes.tiny,
    color: colors.text.faint,
    borderTopWidth: 0.5,
    borderTopColor: colors.border.light,
    paddingTop: spacing.lg,
  },
  pageNumber: {
    fontSize: fontSizes.tiny,
    color: colors.text.faint,
  },
});
