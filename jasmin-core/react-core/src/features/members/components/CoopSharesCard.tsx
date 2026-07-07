import { BankOutlined } from "@ant-design/icons";
import { Alert, Badge, Button, Card, Space, Statistic, Typography } from "antd";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useCommissioningMyMemberDataRetrieve } from "@shared/api/generated/commissioning/commissioning";
import type { Member } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { useCurrency, useDateFormat, useTenant } from "@hooks/index";

const { Text } = Typography;

interface CoopSharesCardProps {
  member: Member;
  /** Opens the CoopSharesModal to view / subscribe ("zeichnen") shares. */
  onManage: () => void;
}

/**
 * Member-detail summary of the member's cooperative equity (Genossenschafts-
 * anteile). Office viewers see the live total + a manage button. The member's
 * own self-view splits confirmed (owned) shares from pending ones they just
 * subscribed and that still await office confirmation.
 */
export default function CoopSharesCard({
  member,
  onManage,
}: CoopSharesCardProps) {
  const { t } = useTranslation();
  const { getSetting } = useTenant();
  const { formatCurrency } = useCurrency();
  const { isMemberOnly } = useRoles();
  const { formatDate } = useDateFormat();

  // ``value_one_coop_share`` is a whole-unit tenant setting (number on the wire).
  const valueOneRaw = getSetting("value_one_coop_share");
  const valueOne = valueOneRaw == null ? 0 : Number(valueOneRaw);

  // Member self-view: fetch the per-share data so we can split confirmed
  // (owned equity) from pending (subscribed, awaiting office confirmation).
  // Office viewers use the server-computed ``coop_shares_total`` on the member.
  const { data: myData } = useCommissioningMyMemberDataRetrieve({
    query: { enabled: isMemberOnly },
  });

  const { confirmedShares, pendingShares, liveShares } = useMemo(() => {
    const live = (myData?.coop_shares ?? []).filter((s) => !s.cancelled_at);
    const sum = (admin: boolean) =>
      live
        .filter((s) => Boolean(s.admin_confirmed) === admin)
        .reduce((acc, s) => acc + Number(s.amount_of_coop_shares ?? 0), 0);
    return {
      confirmedShares: sum(true),
      pendingShares: sum(false),
      liveShares: live,
    };
  }, [myData]);

  // Coop shares still awaiting office confirmation for this member (annotated
  // on the member row). Drives the gold pending badge on the manage button so
  // the sidebar's "N pending" count is traceable to the members who own them.
  const pendingCoopSharesCount = Number(member.coop_shares_pending_count ?? 0);

  // For the member, the headline figure is their CONFIRMED equity; the office
  // figure (``coop_shares_total``) already nets out cancelled shares.
  const totalShares = isMemberOnly
    ? confirmedShares
    : Number(member.coop_shares_total ?? 0);
  const pending = isMemberOnly ? pendingShares : 0;
  const totalValue = totalShares * valueOne;

  // Membership lifecycle: entry date (GenG §30 Eintrittsdatum) and, once the
  // member has left, the exit date. (Per-share payback due / paid-back dates
  // are not in the member self-view bundle — they're shown in the manage modal;
  // surface them here later by adding the two fields to MyDataCoopShare.)
  const entryDate = member.entry_date ?? null;
  const cancelledEffectiveAt = member.cancelled_effective_at ?? null;
  const paybackDueDate = member.payback_due_date;

  return (
    <Card
      className="member-card green-border member-card--blue-title"
      title={t("members.my_membership")}
      extra={
        // A member who has left the co-op can't subscribe new shares (the
        // backend rejects with MemberAlreadyCancelled) — hide the entry point
        // in their self-view. The office keeps it: their modal gates adding.
        isMemberOnly && cancelledEffectiveAt ? null : (
          <Badge
            count={pendingCoopSharesCount}
            color="gold"
            title={t("members.coop_shares_awaiting_confirmation", {
              count: pendingCoopSharesCount,
            })}
          >
            <Button type="primary" onClick={onManage}>
              {t("members.subscribe_coop_shares")}
            </Button>
          </Badge>
        )
      }
    >
      {entryDate && member.admin_confirmed && (
        <Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
          {t("members.entry_date_long")}:{" "}
          <Text strong>{formatDate(entryDate)}</Text>
        </Text>
      )}
      <Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
        {t("members.amount_of_coop_shares")}: <Text strong>{totalShares}</Text>
      </Text>
      <Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
        {t("members.value_of_coop_shares")}:{" "}
        <Text strong>{formatCurrency(totalValue)}</Text>
      </Text>

      {/* Per-purchase payment status (member self-view): paid shares show their
          paid-on date in grey; unpaid ones show the due date in amber. */}
      {isMemberOnly && liveShares.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          {liveShares.map((s) => {
            const amount = Number(s.amount_of_coop_shares ?? 0);
            return (
              <div
                key={s.id}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: 8,
                  padding: "2px 0",
                }}
              >
                <Text type="secondary" style={{ fontSize: "0.9em" }}>
                  {t("members.coop_share_purchase", { n: amount })}
                </Text>
                {s.paid_at ? (
                  <Text type="secondary" style={{ fontSize: "0.9em" }}>
                    {t("members.coop_share_paid_on", {
                      date: formatDate(s.paid_at),
                    })}
                  </Text>
                ) : (
                  <Text type="warning" style={{ fontSize: "0.9em" }}>
                    {s.due_date
                      ? t("members.coop_share_due_by", {
                          date: formatDate(s.due_date),
                        })
                      : t("members.coop_share_not_paid")}
                  </Text>
                )}
              </div>
            );
          })}
        </div>
      )}

      {cancelledEffectiveAt && (
        <Alert
          style={{ marginTop: 16 }}
          type="warning"
          showIcon
          message={
            <>
              <span>
                {t("members.cancelled_effective_at")}:{" "}
                <strong>{formatDate(cancelledEffectiveAt)}</strong> <br />
                {t("members.payback_due_date")}:{" "}
                <strong>{formatDate(paybackDueDate)}</strong>
              </span>
            </>
          }
        />
      )}

      {pending > 0 && (
        <Alert
          style={{ marginTop: 16 }}
          type="info"
          showIcon
          message={t("members.coop_pending_banner", { count: pending })}
        />
      )}
    </Card>
  );
}
