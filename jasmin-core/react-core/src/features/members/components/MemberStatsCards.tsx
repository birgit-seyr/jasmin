import { SummaryStatsCard } from "@shared/ui";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useCommissioningMemberDashboardStatisticsRetrieve } from "@shared/api/generated/commissioning/commissioning";
import { useRoles } from "@shared/auth";
import { useCurrency, useNumberFormat, useTenant } from "@hooks/index";

interface MemberStatsCardsProps {
  /** Fallback member count (non-office / not-yet-loaded): the loaded row count. */
  fallbackMemberCount: number;
  /** Fallback coop-share total: summed over the loaded member rows. */
  fallbackCoopShares: number;
}

/**
 * The "totals at a glance" strips above the members table — a Members strip and
 * a Cooperative-shares strip (each coop count also showing its € worth). Owns
 * its own server-side aggregate (office-only); non-office viewers fall back to
 * the two basic counts the caller derives from the loaded rows.
 */
export default function MemberStatsCards({
  fallbackMemberCount,
  fallbackCoopShares,
}: MemberStatsCardsProps) {
  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const { format } = useNumberFormat();
  const { formatCurrency } = useCurrency();
  const { getSetting } = useTenant();

  const hasCoopShares = !!getSetting("has_coop_shares", true);
  const allowsTrialMembers =
    !!getSetting("allows_trial_subscriptions", true) &&
    !!getSetting("allows_trial_subscriptions_for_trial_members", true);
  const valueOneCoopShareRaw = getSetting("value_one_coop_share");
  const valueOneCoopShare =
    valueOneCoopShareRaw == null ? undefined : Number(valueOneCoopShareRaw);

  const { data: memberStats } = useCommissioningMemberDashboardStatisticsRetrieve(
    { query: { enabled: isOffice } },
  );

  const { memberItems, coopItems } = useMemo(() => {
    if (!memberStats) {
      // Fallback (non-office or not yet loaded): the original basic counts.
      return {
        memberItems: [
          {
            label: t("members.total_members"),
            value: format(fallbackMemberCount, 0),
          },
        ],
        coopItems: hasCoopShares
          ? [
              {
                label: t("members.total_shares"),
                value: fallbackCoopShares
                  ? format(fallbackCoopShares, 0)
                  : "",
              },
            ]
          : [],
      };
    }
    const memberItems = [
      { label: t("statistics.kpi_members"), value: format(memberStats.total_members, 0) },
      { label: t("statistics.kpi_confirmed_members"), value: format(memberStats.confirmed_members, 0) },
      { label: t("statistics.kpi_pending_members"), value: format(memberStats.pending_members, 0) },
      ...(allowsTrialMembers
        ? [
            {
              label: t("statistics.kpi_trial_members"),
              value: format(memberStats.trial_members, 0),
            },
          ]
        : []),
      { label: t("statistics.kpi_cancelled_members"), value: format(memberStats.cancelled_members, 0) },
      {
        label: t("statistics.kpi_average_age"),
        value:
          memberStats.average_age > 0
            ? `${format(memberStats.average_age, 1)} ${t("statistics.years_suffix")}`
            : "—",
      },
    ];
    // Each coop-share count also shows its monetary worth (count ×
    // value_one_coop_share) beneath it, in a smaller muted line.
    const coopValue = (count: number) => (
      <>
        {format(count, 0)}
        {valueOneCoopShare != null && (
          <span
            style={{
              display: "block",
              fontSize: "0.7em",
              fontWeight: 400,
              color: "var(--color-text-muted)",
            }}
          >
            {formatCurrency(count * valueOneCoopShare)}
          </span>
        )}
      </>
    );
    const coopItems = hasCoopShares
      ? [
          { label: t("statistics.kpi_coopshares"), value: coopValue(memberStats.total_coop_shares) },
          { label: t("statistics.kpi_confirmed_coopshares"), value: coopValue(memberStats.confirmed_coop_shares) },
          { label: t("statistics.kpi_pending_coopshares"), value: coopValue(memberStats.pending_coop_shares) },
          { label: t("statistics.kpi_paid_coopshares"), value: coopValue(memberStats.paid_coop_shares) },
          { label: t("statistics.kpi_unpaid_coopshares"), value: coopValue(memberStats.unpaid_coop_shares) },
          { label: t("statistics.kpi_payback_due_coopshares"), value: coopValue(memberStats.payback_due_coop_shares) },
        ]
      : [];
    return { memberItems, coopItems };
  }, [
    memberStats,
    hasCoopShares,
    allowsTrialMembers,
    valueOneCoopShare,
    fallbackMemberCount,
    fallbackCoopShares,
    formatCurrency,
    t,
    format,
  ]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        marginBottom: 12,
      }}
    >
      <SummaryStatsCard
        title={t("statistics.section_members")}
        stats={memberItems}
        equalWidth
      />
      {coopItems.length > 0 && (
        <SummaryStatsCard
          title={t("statistics.section_coopshares")}
          stats={coopItems}
          equalWidth
        />
      )}
    </div>
  );
}
