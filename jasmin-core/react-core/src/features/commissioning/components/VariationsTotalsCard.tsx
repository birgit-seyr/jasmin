import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  useAggregatedVariationsTotals,
  type VariationsTotalEntry,
  type VariationsTotalsFilters,
} from "@features/commissioning/hooks/useAggregatedVariationsTotals";
import { useShareTypeVariations } from "@features/commissioning/hooks/useShareTypeVariations";
import { getShareTypeVariationSizeLabelPure } from "@hooks/index";
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

  // The aggregated entries carry only variation id + size, so we look up each
  // variation's share-type name and sort_order to (a) show the share type as a
  // small label per row and (b) order rows by share type first, then by the
  // variation's sort_order — grouping e.g. all "Ernteanteil" sizes together in
  // their configured order rather than the raw size ordering from the API.
  const { shareTypeVariations } = useShareTypeVariations({});
  const variationMeta = useMemo(
    () =>
      new Map(
        shareTypeVariations.map((variation) => [
          String(variation.id),
          {
            shareTypeName: variation.share_type_name ?? "",
            sortOrder: variation.sort_order ?? 0,
          },
        ]),
      ),
    [shareTypeVariations],
  );

  const entries = useMemo(() => {
    const filtered = hideZero
      ? aggregated.filter((v) => v.totalQuantity > 0)
      : aggregated;
    return [...filtered].sort((a, b) => {
      const metaA = variationMeta.get(String(a.id));
      const metaB = variationMeta.get(String(b.id));
      const nameA = metaA?.shareTypeName ?? "";
      const nameB = metaB?.shareTypeName ?? "";
      if (nameA !== nameB) return nameA.localeCompare(nameB);
      return (metaA?.sortOrder ?? 0) - (metaB?.sortOrder ?? 0);
    });
  }, [aggregated, hideZero, variationMeta]);

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
          {entries.map((variation) => {
            const shareTypeName = variationMeta.get(
              String(variation.id),
            )?.shareTypeName;
            return (
              <li key={String(variation.id)}>
                {shareTypeName && (
                  <span className="variations-totals-card-share-type">
                    {shareTypeName}{" "}
                  </span>
                )}
                {getShareTypeVariationSizeLabelPure(variation.size, t)}:{" "}
                {variation.totalQuantity}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
