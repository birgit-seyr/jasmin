import { CheckCircleOutlined } from "@ant-design/icons";
import { Card, Flex, List, Space, Tag, Typography } from "antd";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { ShareDelivery } from "@shared/api/generated/models";
import {
  organicStatusLabel,
  organicStatusTagColor,
  type OrganicStatus,
  useOrganicGate,
  useShareTypeVariationSizeOptions,
  useTenant,
  useUnitOptions,
} from "@hooks/index";
import { removePurchasedSuffix } from "@shared/utils";

const { Text } = Typography;

const GREEN_SHADES = [
  "var(--color-success)",
  "#142d06ff",
  "#cbf0baff",
  "#95de64",
  "#237804",
  "#a0d911",
];

interface ArticleItem {
  name: string;
  amount: number;
  unit: string;
  size: string;
  sellerName: string | null;
  organicStatus: OrganicStatus | undefined;
}

interface VariationGroup {
  orderedVariation: string;
  orderedVariationType: string;
  physicalVariations: string[];
  articles: ArticleItem[];
  jokerTaken: boolean;
  donationJokerTaken: boolean;
  deliveryStationName: string;
}

interface CurrentWeekDeliveryCardProps {
  shareDeliveries: ShareDelivery[];
  currentWeek: number;
  currentYear: number;
}

const CurrentWeekDeliveryCard = ({
  shareDeliveries,
  currentWeek,
  currentYear,
}: CurrentWeekDeliveryCardProps) => {
  const { t } = useTranslation();
  const { getUnitLabel } = useUnitOptions();
  const { getSetting } = useTenant();
  const usesJokers = getSetting("uses_jokers", true);
  const { enabled: organicGateEnabled } = useOrganicGate();
  const { getShareTypeVariationSizeLabel } = useShareTypeVariationSizeOptions();

  const showSellerName =
    getSetting(
      "show_seller_name_of_share_article_in_share_for_member_on_page",
    ) ?? false;

  const currentWeekByVariation = useMemo(() => {
    const currentWeekDeliveries = shareDeliveries.filter(
      (d) => d.year === currentYear && d.delivery_week === currentWeek,
    );

    const grouped: Record<string, VariationGroup> = {};

    for (const delivery of currentWeekDeliveries) {
      const shareTypeName =
        delivery.ordered_share_type_name ?? delivery.share_type_name ?? "";
      const orderedSize = getShareTypeVariationSizeLabel(
        delivery.ordered_variation_name ??
          delivery.share_type_variation_size ??
          "?",
      );
      const orderedName = shareTypeName
        ? `${shareTypeName} ${orderedSize}`
        : orderedSize;
      const orderedType =
        delivery.ordered_variation_type ??
        delivery.share_type_variation_type ??
        "physical";
      const physicalName = getShareTypeVariationSizeLabel(
        delivery.share_type_variation_size ?? "?",
      );

      if (!grouped[orderedName]) {
        grouped[orderedName] = {
          orderedVariation: orderedName,
          orderedVariationType: orderedType,
          physicalVariations: [],
          articles: [],
          jokerTaken: delivery.joker_taken ?? false,
          donationJokerTaken: delivery.donation_joker_taken ?? false,
          deliveryStationName: delivery.delivery_station_name ?? "",
        };
      }

      if (!grouped[orderedName].physicalVariations.includes(physicalName)) {
        grouped[orderedName].physicalVariations.push(physicalName);
      }

      if (delivery.joker_taken) {
        grouped[orderedName].jokerTaken = true;
      }
      if (delivery.donation_joker_taken) {
        grouped[orderedName].donationJokerTaken = true;
      }

      const shareContent = delivery.share_content ?? [];

      for (const item of shareContent) {
        const existing = grouped[orderedName].articles.find(
          (a) =>
            a.name === item.share_article_name &&
            a.unit === item.unit &&
            a.size === item.size,
        );
        if (existing) {
          existing.amount += Number(item.amount || 0);
        } else {
          grouped[orderedName].articles.push({
            name: item.share_article_name ?? "",
            amount: Number(item.amount || 0),
            unit: item.unit,
            size: item.size ?? "",
            sellerName: item.seller_name_for_member_pages ?? null,
            // Targeted narrow: the schema types ``organic_status`` as a free
            // string; the backend only ever emits the OrganicStatus choices.
            organicStatus:
              (item.organic_status as OrganicStatus | null) ?? undefined,
          });
        }
      }
    }

    return Object.values(grouped);
  }, [shareDeliveries, currentYear, currentWeek, getShareTypeVariationSizeLabel]);

  const renderArticle = (item: ArticleItem, index: number, total: number) => (
    <List.Item
      key={`${item.name}-${item.unit}-${item.size}`}
      style={{
        padding: "2px 0",
        borderBottom:
          index < total - 1 ? "1px solid var(--color-bg-hover)" : "none",
      }}
    >
      <Space size={8} className="w-full">
        <div
          style={{
            width: "8px",
            height: "8px",
            borderRadius: "50%",
            backgroundColor: GREEN_SHADES[index % GREEN_SHADES.length],
            flexShrink: 0,
          }}
        />
        <Text
          style={{
            fontSize: "13px",
            fontWeight: "500",
            color: "var(--color-text-primary)",
            flex: 1,
          }}
        >
          {removePurchasedSuffix(item.name, t)}
          {showSellerName && item.sellerName && (
            <Text
              type="secondary"
              style={{ fontSize: "12px", fontWeight: 400 }}
            >
              {" "}
              ({item.sellerName})
            </Text>
          )}
          {organicGateEnabled && organicStatusTagColor(item.organicStatus) && (
            <>
              {" "}
              <Tag
                color={organicStatusTagColor(item.organicStatus)}
                style={{ marginInlineEnd: 0, fontSize: 11, lineHeight: 1.2 }}
              >
                {organicStatusLabel(t, item.organicStatus)}
              </Tag>
            </>
          )}
        </Text>
        <Text
          style={{
            fontSize: "12px",
            color: "var(--color-text-muted)",
            whiteSpace: "nowrap",
          }}
        >
          {item.amount} {getUnitLabel(item.unit)}
        </Text>
      </Space>
    </List.Item>
  );

  const renderArticles = (group: VariationGroup) => {
    if (group.articles.length === 0) {
      return (
        <Text type="secondary" style={{ fontSize: "12px" }}>
          {t("members.no_share_content_yet")}
        </Text>
      );
    }

    if (showSellerName) {
      const ownArticles = group.articles.filter((a) => !a.sellerName);
      const purchasedArticles = group.articles.filter((a) => !!a.sellerName);

      return (
        <>
          {ownArticles.length > 0 && (
            <>
              <Text
                type="secondary"
                style={{
                  fontSize: "11px",
                  textTransform: "uppercase",
                  letterSpacing: "0.5px",
                }}
              >
                {t("members.from_own_fields")}
              </Text>
              <List
                dataSource={ownArticles}
                split={false}
                renderItem={(item, index) =>
                  renderArticle(item, index, ownArticles.length)
                }
              />
            </>
          )}
          {purchasedArticles.length > 0 && (
            <>
              <Text
                type="secondary"
                style={{
                  fontSize: "11px",
                  textTransform: "uppercase",
                  letterSpacing: "0.5px",
                  marginTop: ownArticles.length > 0 ? "8px" : 0,
                  display: "block",
                }}
              >
                {t("members.purchased")}
              </Text>
              <List
                dataSource={purchasedArticles}
                split={false}
                renderItem={(item, index) =>
                  renderArticle(item, index, purchasedArticles.length)
                }
              />
            </>
          )}
        </>
      );
    }

    return (
      <List
        dataSource={group.articles}
        split={false}
        renderItem={(item, index) =>
          renderArticle(item, index, group.articles.length)
        }
      />
    );
  };

  // Only show this card when the member actually has a delivery THIS week —
  // otherwise hide it entirely (no empty placeholder).
  if (currentWeekByVariation.length === 0) {
    return null;
  }

  return (
    <Card
      title={
        <Space>
          <CheckCircleOutlined />
          {t("members.this_weeks_delivery")} - {t("commissioning.KW")}
          {currentWeek}
        </Space>
      }
      className="member-card blue-border member-card--blue-title"
    >
      {currentWeekByVariation.length > 0 ? (
        <Flex vertical gap="12px">
          {currentWeekByVariation.map((group) => (
            <div
              key={group.orderedVariation}
              style={{
                border: "2px solid #2b620fff",
                borderRadius: "8px",
                padding: "8px 12px",
                background:
                  "linear-gradient(135deg, var(--color-success-bg) 0%, #ffffff 100%)",
                boxShadow: "0 2px 8px rgba(82, 196, 26, 0.1)",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                  marginBottom: group.articles.length > 0 ? "6px" : 0,
                }}
              >
                <Text strong style={{ fontSize: "14px" }}>
                  {group.orderedVariation}
                </Text>
                {group.orderedVariationType === "virtual" && (
                  <Tag color="purple" style={{ margin: 0 }}>
                    {group.physicalVariations.join(" + ")}
                  </Tag>
                )}
                {usesJokers && group.jokerTaken && (
                  <Tag color="darkorange" style={{ margin: 0 }}>
                    Joker
                  </Tag>
                )}
                {group.donationJokerTaken && (
                  <Tag color="darkorange" style={{ margin: 0 }}>
                    {t("members.donation_joker_tag")}
                  </Tag>
                )}
              </div>
              {renderArticles(group)}
            </div>
          ))}
        </Flex>
      ) : (
        <Text type="secondary">{t("members.no_share_content_yet")}</Text>
      )}
    </Card>
  );
};

export default CurrentWeekDeliveryCard;
