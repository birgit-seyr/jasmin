import { ExclamationCircleOutlined } from "@ant-design/icons";
import type { ReactNode } from "react";

export interface DiffCellProps {
  /** Current value rendered (already formatted, e.g. "10.00 €/KG"). */
  value: ReactNode;
  /** True when the local value differs from the upstream snapshot. */
  differs?: boolean | null;
  /**
   * Original (upstream) value. May be a primitive or pre-formatted string.
   * Rendered below the current value when ``differs`` is true and a value
   * is provided.
   */
  original?: unknown;
  /**
   * Optional suffix appended to ``original`` (e.g. " €", " %"). Use when
   * the original is a raw number that needs the same unit decoration as
   * the current value.
   */
  originalSuffix?: string;
  /**
   * Optional formatter for the original value. Receives the raw original
   * and must return what to render. Use for unit-aware formatting.
   */
  formatOriginal?: (original: unknown) => ReactNode;
}

/**
 * Renders a table-cell value with an optional snapshot diff badge below.
 *
 * Used by InvoiceModal & DeliveryNoteModal (both line-item and crate
 * tables) to highlight values that have been edited away from their
 * upstream document snapshot.
 *
 * Styling lives in ``styles/components/diff-cell.css`` and is scoped to
 * ``.jasmin-diff-cell`` so this look only appears where the component is
 * used (i.e. the two modals — not in unrelated tables).
 */
export default function DiffCell({
  value,
  differs,
  original,
  originalSuffix = "",
  formatOriginal,
}: DiffCellProps) {
  const showOriginal =
    !!differs && original !== undefined && original !== null && original !== "";
  const formattedOriginal = showOriginal
    ? formatOriginal
      ? formatOriginal(original)
      : `${String(original)}${originalSuffix}`
    : null;

  return (
    <div className="jasmin-diff-cell">
      <span
        className={
          differs ? "jasmin-diff-cell__value jasmin-diff-cell__value--changed" : "jasmin-diff-cell__value"
        }
      >
        {value}
      </span>
      {showOriginal && (
        <div className="jasmin-diff-cell__original">
          <ExclamationCircleOutlined className="jasmin-diff-cell__icon" />
          {formattedOriginal}
        </div>
      )}
    </div>
  );
}
