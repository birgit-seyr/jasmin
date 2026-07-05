import { List, Modal, Space, Tag, Typography } from "antd";
import { EmptyHint } from "@shared/ui";
import { useTranslation } from "react-i18next";
import type { Subscription } from "@shared/api/generated/models";
import { useDateFormat, useShareTypeVariationSizeOptions } from "@hooks/index";

const { Text } = Typography;

interface PastSubscriptionsModalProps {
  open: boolean;
  /** Already-ended subscriptions (valid_until in the past). */
  subscriptions: Subscription[];
  onClose: () => void;
}

/**
 * Read-only list of a member's past (ended) subscriptions, opened from the
 * subscriptions card. Shows the term, the share type, and how many jokers were
 * taken over that subscription.
 */
export default function PastSubscriptionsModal({
  open,
  subscriptions,
  onClose,
}: PastSubscriptionsModalProps) {
  const { t } = useTranslation();
  const { formatDate } = useDateFormat();
  const { getShareTypeVariationSizeLabel } = useShareTypeVariationSizeOptions();

  return (
    <Modal
      open={open}
      title={t("members.past_subscriptions")}
      onCancel={onClose}
      footer={null}
      width={560}
    >
      {subscriptions.length === 0 ? (
        <EmptyHint>{t("members.no_past_subscriptions")}</EmptyHint>
      ) : (
        <List
          size="small"
          dataSource={subscriptions}
          renderItem={(sub) => {
            const total = sub.amount_of_jokers ?? 0;
            const donationTotal = sub.amount_of_donation_jokers ?? 0;
            return (
              <List.Item key={sub.id}>
                <Space size={8} wrap>
                  <Text type="secondary">
                    {formatDate(sub.valid_from)}
                    {sub.valid_until ? ` – ${formatDate(sub.valid_until)}` : ""}
                  </Text>
                  {sub.quantity > 1 && (
                    <Tag style={{ margin: 0 }}>{sub.quantity}×</Tag>
                  )}
                  <Text strong>
                    {sub.share_type_name}{" "}
                    {getShareTypeVariationSizeLabel(
                      sub.share_type_variation_size ?? "",
                    )}
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
              </List.Item>
            );
          }}
        />
      )}
    </Modal>
  );
}
