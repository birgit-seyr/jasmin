import { HistoryOutlined, PlusOutlined } from "@ant-design/icons";
import { Button, Card, Divider, Space, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Subscription } from "@shared/api/generated/models";
import { EmptyHint, StatusSquare, ToolTipIcon } from "@shared/ui";
import type { StatusSquareVariant } from "@shared/ui";
import { useDateFormat } from "@hooks/index";
import PastSubscriptionsModal from "../modals/PastSubscriptionsModal";
import SubscriptionDetailModal from "../modals/SubscriptionDetailModal";
import { useShareTypeVariationSizeOptions } from "@hooks/useShareTypeVariationSizeOptions";
import "./ActiveSubscriptionsCard.css";

const { Text } = Typography;

interface ActiveSubscriptionsCardProps {
  subscriptions: Subscription[];
  /** When set, a "+ new subscription" button is shown in the header. */
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

  const { getShareTypeVariationSizeLabel } = useShareTypeVariationSizeOptions();

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
        className="active-subscriptions-card__row"
      >
        <StatusSquare variant={variant} title={rowTitle(variant)} />
        <Space size={6} wrap>
          <Text>
            {formatDate(sub.valid_from)}
            {sub.valid_until ? ` – ${formatDate(sub.valid_until)}` : ""}
          </Text>
          {sub.quantity > 1 && (
            <Tag
              color="green"
              className="active-subscriptions-card__tag active-subscriptions-card__tag--quantity"
            >
              {sub.quantity}×
            </Tag>
          )}
          <Text strong>
            {sub.share_type_name}{" "}
            {getShareTypeVariationSizeLabel(sub.share_type_variation_size ?? "")}
          </Text>
          {sub.on_waiting_list && (
            <Space size={2} className="active-subscriptions-card__waiting">
              <Tag color="orange" className="active-subscriptions-card__tag">
                {t("members.on_waiting_list")}
              </Tag>
              <ToolTipIcon title={t("members.waiting_list_tooltip")} />
            </Space>
          )}
          {total > 0 && (
            <Text className="active-subscriptions-card__jokers">
              (
              {t("members.jokers_taken", {
                taken: sub.jokers_taken ?? 0,
                total,
              })}
              )
            </Text>
          )}
          {donationTotal > 0 && (
            <Text className="active-subscriptions-card__jokers">
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
      className="member-card blue-border member-card--blue-title active-subscriptions-card"
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
          <Divider
            className="active-subscriptions-card__divider active-subscriptions-card__divider--first"
            orientation="left"
            plain
          >
            <Text
              type="secondary"
              className="active-subscriptions-card__group-label"
            >
              {t("members.active_subscriptions")}
            </Text>
          </Divider>
          {active.map((sub) => renderRow(sub, "active"))}
        </>
      )}

      {coming.length > 0 && (
        <>
          <Divider
            className="active-subscriptions-card__divider"
            orientation="left"
            plain
          >
            <Text
              type="secondary"
              className="active-subscriptions-card__group-label"
            >
              {t("members.coming_subscriptions")}
            </Text>
          </Divider>
          {coming.map((sub) => renderRow(sub, "upcoming"))}
        </>
      )}

      {pending.length > 0 && (
        <>
          <Divider
            className="active-subscriptions-card__divider"
            orientation="left"
            plain
          >
            <Text
              type="secondary"
              className="active-subscriptions-card__group-label"
            >
              {t("members.pending_subscriptions")}
            </Text>
          </Divider>
          {pending.map((sub) => renderRow(sub, "pending"))}
        </>
      )}

      {past.length > 0 && (
        <div className="active-subscriptions-card__past">
          <Button
            size="small"
            type="link"
            icon={<HistoryOutlined />}
            onClick={() => setPastOpen(true)}
            className="active-subscriptions-card__past-button"
          >
            {t("members.show_past_subscriptions", { count: past.length })}
          </Button>
        </div>
      )}

      {active.length === 0 &&
        coming.length === 0 &&
        pending.length === 0 &&
        past.length === 0 && (
          <EmptyHint>{t("members.no_active_subscriptions")}</EmptyHint>
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
