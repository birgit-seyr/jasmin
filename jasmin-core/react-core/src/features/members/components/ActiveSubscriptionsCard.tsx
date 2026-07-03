import { HistoryOutlined, PlusOutlined } from "@ant-design/icons";
import { Button, Card, Divider, Empty, Space, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Subscription } from "@shared/api/generated/models";
import { StatusSquare } from "@shared/ui";
import type { StatusSquareVariant } from "@shared/ui";
import { useDateFormat } from "@hooks/index";
import PastSubscriptionsModal from "../modals/PastSubscriptionsModal";
import SubscriptionDetailModal from "../modals/SubscriptionDetailModal";

const { Text } = Typography;

interface ActiveSubscriptionsCardProps {
  subscriptions: Subscription[];
  /** When set, a "+ new subscription" button is shown in the header (the
   *  standalone SubscriptionsCard was folded into this card). */
  onNewSubscription?: () => void;
  /** Hide the new-subscription button (e.g. a cancelled member). */
  canAdd?: boolean;
}

const ActiveSubscriptionsCard = ({
  subscriptions,
  onNewSubscription,
  canAdd = true,
}: ActiveSubscriptionsCardProps) => {
  const { t } = useTranslation();
  const { formatDate } = useDateFormat();
  const [pastOpen, setPastOpen] = useState(false);
  const [selected, setSelected] = useState<Subscription | null>(null);

  const { active, coming, pending, past } = useMemo(() => {
    const today = dayjs().format("YYYY-MM-DD");
    const active: Subscription[] = [];
    const coming: Subscription[] = [];
    const pending: Subscription[] = [];
    const past: Subscription[] = [];
    for (const sub of subscriptions) {
      // Past: had a term that has already ended (regardless of confirm state).
      if (sub.valid_until && sub.valid_until < today) {
        past.push(sub);
        continue;
      }
      if (!sub.admin_confirmed) {
        // Not yet confirmed — surface genuine pending ones (not rejected /
        // cancelled) so the office can act on them.
        if (!sub.admin_rejected_at && !sub.cancelled_at) {
          pending.push(sub);
        }
        continue;
      }
      if (sub.valid_from > today) {
        coming.push(sub); // confirmed, not yet started
      } else {
        active.push(sub); // confirmed, started, not ended
      }
    }
    return { active, coming, pending, past };
  }, [subscriptions]);

  const rowTitle = (variant: StatusSquareVariant) => {
    if (variant === "active") return t("members.currently_active");
    if (variant === "upcoming") return t("members.future_active");
    return t("members.status_pending");
  };

  const renderRow = (sub: Subscription, variant: StatusSquareVariant) => {
    const total = sub.amount_of_jokers ?? 0;
    const donationTotal = sub.amount_of_donation_jokers ?? 0;
    return (
      <div
        key={sub.id}
        role="button"
        tabIndex={0}
        onClick={() => setSelected(sub)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setSelected(sub);
          }
        }}
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 8,
          padding: "6px 0",
          borderBottom: "1px solid var(--color-bg-subtle)",
          cursor: "pointer",
        }}
      >
        <StatusSquare variant={variant} title={rowTitle(variant)} />
        <Space size={6} wrap>
          <Text>
            {formatDate(sub.valid_from)}
            {sub.valid_until ? ` – ${formatDate(sub.valid_until)}` : ""}
          </Text>
          {sub.quantity > 1 && (
            <Tag color="green" style={{ margin: 0, fontWeight: 600 }}>
              {sub.quantity}×
            </Tag>
          )}
          <Text strong>
            {sub.share_type_name} {sub.share_type_variation_size}
          </Text>
          {total > 0 && (
            <Text style={{ color: "var(--color-joker)", fontSize: 12 }}>
              (
              {t("members.jokers_taken", {
                taken: sub.jokers_taken ?? 0,
                total,
              })}
              )
            </Text>
          )}
          {donationTotal > 0 && (
            <Text style={{ color: "var(--color-joker)", fontSize: 12 }}>
              (
              {t("members.donation_jokers_taken", {
                taken: sub.donation_jokers_taken ?? 0,
                total: donationTotal,
              })}
              )
            </Text>
          )}
        </Space>
      </div>
    );
  };

  return (
    <Card
      title={<Space size={6}>{t("members.my_subscriptions")}</Space>}
      className="member-card blue-border member-card--blue-title"
      styles={{ body: { padding: "12px 16px" } }}
      extra={
        canAdd && onNewSubscription ? (
          <Button
            type="primary"
            size="small"
            icon={<PlusOutlined />}
            onClick={onNewSubscription}
          >
            {t("members.create_subscription")}
          </Button>
        ) : undefined
      }
    >
      {active.length > 0 && (
        <>
          <Divider style={{ margin: "0 0 4px" }} orientation="left" plain>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t("members.active_subscriptions")}
            </Text>
          </Divider>
          {active.map((sub) => renderRow(sub, "active"))}
        </>
      )}

      {coming.length > 0 && (
        <>
          <Divider style={{ margin: "12px 0 4px" }} orientation="left" plain>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t("members.coming_subscriptions")}
            </Text>
          </Divider>
          {coming.map((sub) => renderRow(sub, "upcoming"))}
        </>
      )}

      {pending.length > 0 && (
        <>
          <Divider style={{ margin: "12px 0 4px" }} orientation="left" plain>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t("members.pending_subscriptions")}
            </Text>
          </Divider>
          {pending.map((sub) => renderRow(sub, "pending"))}
        </>
      )}

      {past.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <Button
            size="small"
            type="link"
            icon={<HistoryOutlined />}
            onClick={() => setPastOpen(true)}
            style={{ paddingLeft: 0 }}
          >
            {t("members.show_past_subscriptions", { count: past.length })}
          </Button>
        </div>
      )}

      {active.length === 0 &&
        coming.length === 0 &&
        pending.length === 0 &&
        past.length === 0 && (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={t("members.no_active_subscriptions")}
          />
        )}

      <PastSubscriptionsModal
        open={pastOpen}
        subscriptions={past}
        onClose={() => setPastOpen(false)}
      />

      <SubscriptionDetailModal
        subscription={selected}
        onClose={() => setSelected(null)}
      />
    </Card>
  );
};

export default ActiveSubscriptionsCard;
