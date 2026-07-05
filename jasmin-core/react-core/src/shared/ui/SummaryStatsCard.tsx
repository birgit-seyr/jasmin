/**
 * Reusable header strip for "totals at a glance" — the small boxed
 * row that sits between the page filters and the table on pages like
 * MemberLoans and Members. Each cell is a label + value pair; the grid
 * lets multiple stats sit side-by-side and wrap on narrow viewports.
 *
 * Style lives in ``styles/components/summary-stats-card.css`` and uses
 * design tokens for background / border / text so dark mode works
 * without per-callsite overrides.
 */

import type { ReactNode } from "react";

export interface SummaryStat {
  /** Human-readable label (already translated). */
  label: ReactNode;
  /** The number / string to render. Pre-format on the caller's side. */
  value: ReactNode;
}

interface SummaryStatsCardProps {
  stats: SummaryStat[];
  /** Optional caption rendered above the stats row (already translated). */
  title?: ReactNode;
  /**
   * Lay the stats out as an even grid where every cell has the SAME width
   * (default: each cell sizes to its own content). Use when the labels are of
   * comparable importance and a tidy aligned grid reads better than a compact
   * content-sized row.
   */
  equalWidth?: boolean;
}

export default function SummaryStatsCard({
  stats,
  title,
  equalWidth = false,
}: SummaryStatsCardProps) {
  return (
    <div
      className={
        equalWidth
          ? "summary-stats-card summary-stats-card--equal"
          : "summary-stats-card"
      }
    >
      {title != null && (
        <div className="summary-stats-card__title">{title}</div>
      )}
      {stats.map((stat, idx) => (
        <div key={idx} className="summary-stats-card__item">
          <div className="summary-stats-card__label">{stat.label}</div>
          <div className="summary-stats-card__value">{stat.value}</div>
        </div>
      ))}
    </div>
  );
}
