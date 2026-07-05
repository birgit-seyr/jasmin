import type { SummaryRow } from "./BasicEditableTable/types";

/** The style shape a ``SummaryRow`` accepts (background / font size / … ). */
type SummaryRowStyle = NonNullable<SummaryRow["style"]>;

/**
 * Canonical styling for EditableTable summary rows — the SINGLE place to change
 * their background / font size / weight. Pass as a ``SummaryRow.style``. When a
 * summary row omits ``style`` the table falls back to its built-in default; use
 * this constant instead so every summary row reads consistently and one edit
 * here restyles them all.
 */
export const SUMMARY_ROW_STYLE: SummaryRowStyle = {
  backgroundColor: "var(--color-bg-base)",
  fontSize: "1.1em",
};

/**
 * Highlight variant for secondary / reference summary rows (e.g. historical
 * averages) — visually distinct from the primary totals above.
 */
export const SUMMARY_ROW_STYLE_HIGHLIGHT: SummaryRowStyle = {
  backgroundColor: "var(--color-info-bg)",
  fontSize: "1.0em",
  fontStyle: "italic",
};
