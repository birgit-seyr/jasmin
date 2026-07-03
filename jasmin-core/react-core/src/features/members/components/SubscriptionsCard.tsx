import { PlusOutlined } from "@ant-design/icons";
import { Card, Flex, Space, Typography } from "antd";
import { useTranslation } from "react-i18next";
import type { Subscription } from "@shared/api/generated/models";

const { Text } = Typography;

interface SubscriptionsCardProps {
  subscriptions: Subscription[];
  shareTypeNames: string[];
  onNewSubscription: () => void;
}

const SubscriptionsCard = ({
  subscriptions: _subscriptions,
  shareTypeNames,
  onNewSubscription,
}: SubscriptionsCardProps) => {
  const { t } = useTranslation();

  const teaserText =
    shareTypeNames.length > 0 ? shareTypeNames.join(", ") + " …" : "";

  return (
    <Card
      hoverable
      onClick={onNewSubscription}
      className="member-card--top-spaced"
      style={{
        marginTop: 24,
        cursor: "pointer",
        background:
          "linear-gradient(135deg, var(--color-success-bg) 0%, #e6f7ff 100%)",
        borderColor: "var(--color-primary)",
      }}
      styles={{ body: { padding: "16px 20px" } }}
    >
      <Flex align="center" gap={16}>
        <div
          style={{
            width: 48,
            height: 48,
            borderRadius: "50%",
            background: "var(--gradient-primary)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        ></div>
        <div className="flex-1">
          <Space>
            <Text strong style={{ fontSize: 16 }}>
              {t("members.additional_subscription")}
            </Text>
            <PlusOutlined style={{ color: "var(--color-primary)" }} />
          </Space>
          {teaserText && (
            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {t("members.additional_subscription_teaser")} {teaserText}
              </Text>
            </div>
          )}
        </div>
      </Flex>
    </Card>
  );
};

export default SubscriptionsCard;
