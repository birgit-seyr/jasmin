import { SummaryStatsCard, type SummaryStat } from "@shared/ui";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  useSubscriptionVariationStats,
  type StatusSummary,
} from "@features/abos/hooks/useSubscriptionVariationStats";

interface SubscriptionStatsCardsProps {
  subscriptions: Parameters<typeof useSubscriptionVariationStats>[0];
  variations: Parameters<typeof useSubscriptionVariationStats>[1];
}

/**
 * The "totals at a glance" strip above the subscriptions table: one compact row
 * of three tiles — Active / Future / Waiting-list — each showing its total with
 * the per-variation split as small colour-dotted rows beneath (same colours as
 * the dashboard graph). Renders nothing until the catalogue has variations.
 */
export default function SubscriptionStatsCards({
  subscriptions,
  variations,
}: SubscriptionStatsCardsProps) {
  const { t } = useTranslation();
  const { variationInfo, snapshot } = useSubscriptionVariationStats(
    subscriptions,
    variations,
  );

  const subscriptionTiles = useMemo<SummaryStat[]>(() => {
    const breakdown = (summary: StatusSummary) => {
      const rows = [...variationInfo.values()]
        .map((info) => ({ info, qty: summary.byVariation.get(info.id) ?? 0 }))
        .filter((r) => r.qty > 0);
      if (rows.length === 0) return null;
      return (
        <div style={{ marginTop: 6 }}>
          {rows.map(({ info, qty }) => (
            <div
              key={info.id}
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: 8,
                fontSize: "0.7em",
                fontWeight: 400,
                color: "var(--color-text-muted)",
                padding: "1px 0",
              }}
            >
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 5,
                  minWidth: 0,
                }}
              >
                <span
                  style={{
                    width: 7,
                    height: 7,
                    borderRadius: "50%",
                    background: info.color,
                    flex: "0 0 auto",
                  }}
                />
                <span
                  style={{
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {info.label}
                </span>
              </span>
              <span>{qty}</span>
            </div>
          ))}
        </div>
      );
    };
    const cell = (summary: StatusSummary) => (
      <>
        {summary.total}
        {breakdown(summary)}
      </>
    );
    return [
      {
        label: t("statistics.kpi_active_subscriptions"),
        value: cell(snapshot.active),
      },
      {
        label: t("statistics.kpi_future_subscriptions"),
        value: cell(snapshot.future),
      },
      {
        label: t("statistics.kpi_waiting_list"),
        value: cell(snapshot.waiting),
      },
    ];
  }, [snapshot, variationInfo, t]);

  if (variationInfo.size === 0) return null;

  return (
    <div style={{ marginBottom: 12 }}>
      <SummaryStatsCard stats={subscriptionTiles} equalWidth />
    </div>
  );
}
