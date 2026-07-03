import { StyleSheet } from "@react-pdf/renderer";
import { pdfTheme } from "./pdfTheme";

const { colors, fontSizes, spacing } = pdfTheme;

/**
 * Table primitives for the generic, column-driven table (``BaseListPDF`` /
 * ``extractPdfColumns``) and the harvest crate-summary table. These are the
 * ``baseStyles``-shaped keys that ``extractPdfColumns(...).renderHeader`` /
 * ``renderRow`` expect. Page chrome (header/footer/title) is NOT here — those
 * PDFs use the shared ``ListPDFHeader``/``ListPDFFooter`` and ``listStyles``,
 * same as every hand-rolled list PDF. All values derive from ``./pdfTheme.ts``
 * so the Clean Hairline look stays in sync with ``./listPdfBase.ts``.
 */
export const baseStyles = StyleSheet.create({
  // Clean Hairline: no outer box, no vertical gridlines — rows separated by
  // hairline dividers under a single header underline.
  table: {
    display: "flex",
    width: "auto",
  },
  tableRow: {
    flexDirection: "row",
    minHeight: 26,
  },
  tableColHeader: {
    borderStyle: "solid",
    borderColor: colors.border.default,
    borderBottomWidth: 1,
    paddingTop: spacing.sm,
    paddingBottom: spacing.sm,
    paddingLeft: spacing.md,
    paddingRight: spacing.md,
  },
  tableColHeaderLast: {},
  tableCol: {
    borderStyle: "solid",
    borderColor: colors.border.light,
    borderBottomWidth: 0.5,
    paddingTop: 5,
    paddingBottom: 5,
    paddingLeft: spacing.md,
    paddingRight: spacing.md,
  },
  tableColLast: {},
  tableCellHeaderCenter: {
    fontSize: fontSizes.tiny,
    fontWeight: 700,
    color: colors.text.muted,
    textTransform: "uppercase",
    letterSpacing: 0.6,
    textAlign: "center",
  },
  tableCellHeaderLeft: {
    fontSize: fontSizes.tiny,
    fontWeight: 700,
    color: colors.text.muted,
    textTransform: "uppercase",
    letterSpacing: 0.6,
    textAlign: "left",
  },
  tableCell: {
    fontSize: fontSizes.smaller,
    color: colors.text.strong,
    textAlign: "center",
  },
  tableCellLeft: {
    textAlign: "left",
  },
  tableCellAmount: {
    fontWeight: "bold",
    color: colors.accent.success,
  },
});
