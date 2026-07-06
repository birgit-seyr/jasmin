import { CheckCircleFilled } from "@ant-design/icons";
import { Badge, Card, Col, Flex, Row, Tag, Typography } from "antd";
import DOMPurify from "dompurify";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useCurrency, useShareTypeVariationSizeOptions } from "@hooks/index";
import type { ShareTypeVariationOption } from "@hooks/useAllShareTypeVariations";

const { Title, Text } = Typography;

// Office-authored rich text often glues words with &nbsp; — swap to normal
// spaces so it wraps at word boundaries, and sanitise (this renders HTML).
const cleanDescriptionHtml = (html: string): string =>
  DOMPurify.sanitize(html)
    .replace(/&nbsp;/gi, " ")
    .replace(/\u00a0/g, " ");

interface ShareTypeVariationPickerGridProps {
  variations: ShareTypeVariationOption[];
  onSelect: (variation: ShareTypeVariationOption) => void;
  /** Variation value → active quantity: drives the "N×" already-subscribed badge. */
  activeQuantityByVariation?: Record<string, number>;
  /** When set, the matching card is highlighted (pick-then-confirm flows). */
  selectedValue?: string | number;
  /** Variation values that are full for the term — dimmed with a sold-out tag. */
  soldOutValues?: Set<string>;
}

/**
 * The share-type-variation picker grid: variations grouped by share type, each
 * a rich card (picture/size, price per delivery, office description, the
 * "already subscribed" badge). Extracted from ``NewSubscriptionModal`` so the
 * public registration wizard reuses the SAME cards + info. The modal advances
 * on select; registration passes ``selectedValue`` to highlight the pick and
 * confirm with a quantity afterwards.
 */
export default function ShareTypeVariationPickerGrid({
  variations,
  onSelect,
  activeQuantityByVariation = {},
  selectedValue,
  soldOutValues,
}: ShareTypeVariationPickerGridProps) {
  const { t } = useTranslation();
  const { currencySymbol } = useCurrency();
  const { getShareTypeVariationSizeLabel } = useShareTypeVariationSizeOptions();

  const variationsByType = useMemo(() => {
    const groups: Record<
      string,
      { typeName: string; variations: ShareTypeVariationOption[] }
    > = {};
    for (const variation of variations) {
      const key = variation.share_type;
      if (!groups[key]) {
        groups[key] = {
          typeName: variation.share_type_name ?? "",
          variations: [],
        };
      }
      groups[key].variations.push(variation);
    }
    for (const group of Object.values(groups)) {
      group.variations.sort(
        (a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0),
      );
    }
    return Object.values(groups);
  }, [variations]);

  return (
    <div>
      {variationsByType.map((group) => (
        <div key={group.typeName} style={{ marginBottom: 24 }}>
          <Title level={5} style={{ marginBottom: 12 }}>
            {group.typeName}
          </Title>
          <Row gutter={[12, 12]}>
            {group.variations.map((variation) => {
              const activeQty = activeQuantityByVariation[variation.value] ?? 0;
              const selected =
                selectedValue != null &&
                String(selectedValue) === String(variation.value);
              const soldOut =
                soldOutValues?.has(String(variation.value)) ?? false;
              return (
                <Col xs={24} sm={12} key={variation.value}>
                  <Badge
                    count={activeQty > 0 ? `${activeQty}×` : 0}
                    color="#226c47"
                    offset={[-8, 8]}
                  >
                    <Card
                      hoverable
                      onClick={() => onSelect(variation)}
                      styles={{ body: { padding: 12 } }}
                      style={{
                        height: "100%",
                        opacity: soldOut ? 0.6 : 1,
                        borderColor: selected
                          ? "var(--color-primary)"
                          : undefined,
                        borderWidth: selected ? 2 : undefined,
                      }}
                    >
                      <Flex gap={12} align="flex-start">
                        {variation.picture ? (
                          <img
                            src={variation.picture}
                            alt={variation.label}
                            className="new-subscription-card-image"
                          />
                        ) : (
                          <div className="new-subscription-card-placeholder">
                            {getShareTypeVariationSizeLabel(
                              variation.size ?? "",
                            )}
                          </div>
                        )}
                        <div className="flex-min">
                          <Text strong style={{ fontSize: 14 }}>
                            {getShareTypeVariationSizeLabel(
                              variation.size ?? "",
                            )}
                          </Text>
                          {variation.active_price_per_delivery && (
                            <div>
                              <Text type="secondary" style={{ fontSize: 13 }}>
                                {variation.active_price_per_delivery}{" "}
                                {currencySymbol} / {t("abos.delivery")}
                              </Text>
                            </div>
                          )}
                          {soldOut && (
                            <div style={{ marginTop: 4 }}>
                              <Tag color="red">{t("abos.sold_out")}</Tag>
                            </div>
                          )}
                          {variation.description && (
                            <div
                              style={{
                                fontSize: 12,
                                marginTop: 4,
                                color: "rgba(0, 0, 0, 0.45)",
                                display: "-webkit-box",
                                WebkitLineClamp: 2,
                                WebkitBoxOrient: "vertical",
                                overflow: "hidden",
                                overflowWrap: "break-word",
                              }}
                              dangerouslySetInnerHTML={{
                                __html: cleanDescriptionHtml(
                                  variation.description,
                                ),
                              }}
                            />
                          )}
                        </div>
                        <CheckCircleFilled
                          style={{
                            color: "var(--color-primary)",
                            fontSize: 20,
                            opacity: selected || activeQty > 0 ? 1 : 0.15,
                          }}
                        />
                      </Flex>
                    </Card>
                  </Badge>
                </Col>
              );
            })}
          </Row>
        </div>
      ))}
    </div>
  );
}
