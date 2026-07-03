import { useTranslation } from "react-i18next";
import {
  useAggregatedVariationsTotals,
  type VariationsTotalEntry,
  type VariationsTotalsFilters,
} from "@features/commissioning/hooks/useAggregatedVariationsTotals";
import ToolTipIcon from "@shared/ui/ToolTipIcon";

export type { VariationsTotalEntry, VariationsTotalsFilters };

interface VariationsTotalsCardProps {
  /** Filters used to fetch totals internally. */
  filters?: VariationsTotalsFilters;
  title?: string;
  tooltip?: string;
  /** When true, only entries with totalQuantity > 0 are rendered. Default: true. */
  hideZero?: boolean;
  /** Text shown when there are no entries to display. */
  emptyText?: string;
  className?: string;
}

/**
 * Small reusable summary card listing variation sizes and their totals.
 * Always renders (even when empty) so surrounding layout doesn't shift.
 *
 * Always autonomous: pass `filters` and the card fetches its own data via
 * :func:`useAggregatedVariationsTotals`. If ``filters.delivery_day`` is an
 * array of IDs, totals are aggregated across them — useful for the
 * harvesting view where one harvest day serves multiple delivery days.
 */
export default function VariationsTotalsCard({
  filters,
  title,
  tooltip,
  hideZero = true,
  emptyText,
  className,
}: VariationsTotalsCardProps) {
  const { t } = useTranslation();
  const { entries: aggregated } = useAggregatedVariationsTotals(filters);

  const entries = hideZero
    ? aggregated.filter((v) => v.totalQuantity > 0)
    : aggregated;

  const cardClassName = ["variations-totals-card", className]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={cardClassName}>
      <div className="variations-totals-card-header">
        <strong>{title ?? t("commissioning.variations_totals")}</strong>
        {tooltip && <ToolTipIcon title={tooltip} />}
      </div>
      {entries.length === 0 ? (
        <div className="variations-totals-card-empty">
          {emptyText ?? t("common.no_data")}
        </div>
      ) : (
        <ul className="variations-totals-card-list">
          {entries.map((variation) => (
            <li key={String(variation.id)}>
              {t(`commissioning.${variation.size}`)}: {variation.totalQuantity}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
