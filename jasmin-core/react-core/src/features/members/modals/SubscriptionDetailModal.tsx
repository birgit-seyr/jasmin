import { Alert, Descriptions, Modal, Tag, Typography } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Subscription } from "@shared/api/generated/models";
import { useCurrency, useDateFormat } from "@hooks/index";
import { deliveryCycleLabel, paymentCycleLabel } from "@shared/utils/cycleLabels";
import DeliveryStationMemberModal from "./DeliveryStationMemberModal";

const { Link } = Typography;

interface SubscriptionDetailModalProps {
  /** The subscription to show. ``null`` closes the modal. */
  subscription: Subscription | null;
  onClose: () => void;
}

/** Read-only detail view of a single subscription (opened by clicking a row in
 * ActiveSubscriptionsCard). The delivery station links to its station-day info. */
export default function SubscriptionDetailModal({
  subscription,
  onClose,
}: SubscriptionDetailModalProps) {
  const { t } = useTranslation();
  const { formatDate } = useDateFormat();
  const { currencySymbol } = useCurrency();
  const [stationDayId, setStationDayId] = useState<string | null>(null);

  // This modal is mounted permanently by ActiveSubscriptionsCard (only the
  // ``subscription`` prop toggles), so the nested station-day modal's state
  // would otherwise survive an outer close / a switch to another subscription
  // and re-open stale. Reset it whenever the shown subscription changes.
  useEffect(() => {
    setStationDayId(null);
  }, [subscription?.id]);

  const statusTag = (sub: Subscription) => {
    if (sub.cancelled_at)
      return <Tag color="default">{t("members.status_cancelled")}</Tag>;
    if (sub.admin_rejected_at)
      return <Tag color="red">{t("members.status_rejected")}</Tag>;
    if (sub.admin_confirmed)
      return <Tag color="green">{t("members.status_confirmed")}</Tag>;
    return <Tag color="gold">{t("members.status_pending")}</Tag>;
  };

  return (
    <Modal
      open={!!subscription}
      onCancel={onClose}
      onOk={onClose}
      footer={null}
      title={t("members.subscription_details")}
    >
      {subscription && (
        <>
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label={t("members.share_type")}>
              {subscription.share_type_name}{" "}
              {subscription.share_type_variation_size}
            </Descriptions.Item>
            <Descriptions.Item label={t("members.term")}>
              {formatDate(subscription.valid_from)}
              {subscription.valid_until
                ? ` – ${formatDate(subscription.valid_until)}`
                : ""}
            </Descriptions.Item>
            <Descriptions.Item label={t("members.status")}>
              {statusTag(subscription)}
            </Descriptions.Item>
            <Descriptions.Item label={t("members.quantity")}>
              {subscription.quantity}×
            </Descriptions.Item>
            <Descriptions.Item label={t("members.price_per_delivery")}>
              {subscription.price_per_delivery} {currencySymbol}
            </Descriptions.Item>
            <Descriptions.Item label={t("commissioning.delivery_cycle")}>
              {deliveryCycleLabel(t, subscription.delivery_cycle)}
            </Descriptions.Item>
            <Descriptions.Item label={t("members.payment_cycle")}>
              {paymentCycleLabel(t, subscription.payment_cycle_name)}
            </Descriptions.Item>
            <Descriptions.Item label={t("members.delivery_station")}>
              {subscription.default_delivery_station_day ? (
                <Link
                  onClick={() =>
                    setStationDayId(
                      subscription.default_delivery_station_day ?? null,
                    )
                  }
                >
                  {subscription.delivery_station_name ??
                    t("delivery_stations.show_station")}
                </Link>
              ) : (
                (subscription.delivery_station_name ?? "—")
              )}
            </Descriptions.Item>
            {(subscription.amount_of_jokers ?? 0) > 0 && (
              <Descriptions.Item label={t("members.jokers")}>
                {t("members.jokers_taken", {
                  taken: subscription.jokers_taken ?? 0,
                  total: subscription.amount_of_jokers ?? 0,
                })}
              </Descriptions.Item>
            )}
          </Descriptions>

          {subscription.requires_optin && (
            <Alert
              type="info"
              showIcon
              style={{ marginTop: 12 }}
              message={t("members.optin_required")}
            />
          )}

          <DeliveryStationMemberModal
            stationDayId={stationDayId}
            onClose={() => setStationDayId(null)}
          />
        </>
      )}
    </Modal>
  );
}
