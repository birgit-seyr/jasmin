/**
 * Canonical design tokens for every PDF rendered out of
 * ``components/pdfs/exports``. Two stylesheets — ``baseStyles.ts``
 * (table primitives for the column-driven BaseListPDF) and
 * ``listPdfBase.ts`` (for the list-style PDFs) — both derive from
 * this theme. Inline hex
 * literals across the PDF documents should reference these tokens
 * instead of hard-coding values.
 *
 * What's NOT here, intentionally:
 *   - Per-document page-accent colors (pastel header backgrounds
 *     for Harvest/Purchase/Cleaning/…). Those are intentional
 *     per-PDF choices that callers pass via the ``backgroundColor``
 *     prop, not design tokens.
 *
 * Adding new tokens: add the semantic name + the hex/number ONCE
 * here. Updating existing tokens cascades to both stylesheets
 * (and any PDF that references the theme directly).
 */
export const pdfTheme = {
  colors: {
    // Surfaces
    page: "#FFFFFF",
    cardSurface: "#f9f9f9",
    tableHeader: "#E8E6EA",
    rowAlt: "#f4f4f6",
    footerSurface: "#F8FAFC",

    // Text — primary > strong > secondary > tertiary > muted > faint
    text: {
      primary: "#111",
      strong: "#1F2937",
      secondary: "#444",
      tertiary: "#333",
      muted: "#666",
      faint: "#999",
    },

    // Borders — by weight
    border: {
      heavy: "#222",
      strong: "#999",
      default: "#D1D5DB",
      light: "#ddd",
      lighter: "#E2E8F0",
      faint: "#ccc",
    },

    // Brand
    brand: "#1d603e",

    // Status / accent
    accent: {
      success: "#059669",
    },
  },

  fontSizes: {
    title: 16,
    subtitle: 12,
    body: 11,
    small: 10,
    smaller: 9,
    tiny: 8,
  },

  spacing: {
    xxs: 2,
    xs: 4,
    sm: 6,
    md: 8,
    lg: 10,
    xl: 12,
    xxl: 16,
    xxxl: 18,
    page: 40,
    pageTop: 50,
  },
} as const;

export type PdfTheme = typeof pdfTheme;
