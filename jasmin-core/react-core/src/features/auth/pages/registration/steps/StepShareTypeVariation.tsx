import { Alert, Button, Card, Flex, Space, Typography } from "antd";
import dayjs from "dayjs";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import NewSubscriptionModal, {
  type SubscriptionIntent,
} from "@features/abos/modals/NewSubscriptionModal";
import {
  useAllShareTypeVariations,
  useCurrency,
  useShareTypes,
  useShareTypeVariationSizeOptions,
} from "@hooks/index";
import type { StepProps } from "../types";

const { Paragraph, Text } = Typography;

/**
 * Step 2 — pick a share. Opens the SAME ``NewSubscriptionModal`` the office
 * uses (in ``mode="public"``): identical picker cards, prices, capacity/
 * sold-out, delivery-station map + solidarity price. It writes nothing — the
 * chosen configuration comes back as intent and the office materialises the
 * real (capacity-checked) subscription on confirm.
 */
export default function StepShareTypeVariation({
  data,
  update,
  next,
  back,
}: StepProps) {
  const { t } = useTranslation();
  const { formatCurrency } = useCurrency();
  const { getShareTypeVariationSizeLabel } = useShareTypeVariationSizeOptions();
  const [modalOpen, setModalOpen] = useState(false);

  // Look up the chosen variation for the summary line (deduped — the modal
  // fetches the same catalog under the same query keys).
  const today = dayjs().format("YYYY-MM-DD");
  const { shareTypes } = useShareTypes({
    active_at_date: today,
    include_future: true,
  });
  const shareTypeRefs: { id?: string | null }[] = shareTypes;
  const { shareTypeVariations } = useAllShareTypeVariations(shareTypeRefs, {
    active_at_date: today,
    include_future: true,
  });

  const chosenId = data.share_type_variation_id;
  const chosenVariation = useMemo(
    () => shareTypeVariations.find((v) => String(v.value) === String(chosenId)),
    [shareTypeVariations, chosenId],
  );

  const handleIntent = (intent: SubscriptionIntent) => {
    update({
      share_type_variation_id: intent.share_type_variation_id,
      quantity: intent.quantity,
      default_delivery_station_day: intent.default_delivery_station_day,
      price_per_delivery: intent.price_per_delivery,
      payment_cycle: intent.payment_cycle,
      valid_from: intent.valid_from,
      valid_until: intent.valid_until,
      is_trial: intent.is_trial,
    });
    setModalOpen(false);
  };

  const price =
    data.price_per_delivery ?? chosenVariation?.active_price_per_delivery;

  return (
    <>
      <Paragraph>{t("auth.registration.variation.intro")}</Paragraph>

      {chosenId ? (
        <Card
          size="small"
          style={{
            marginBottom: 16,
            borderColor: "var(--color-primary)",
            borderWidth: 2,
          }}
        >
          <Flex justify="space-between" align="center" gap="middle" wrap>
            <Space direction="vertical" size={0}>
              <Text strong>
                {data.quantity ?? 1} ×{" "}
                {chosenVariation
                  ? `${chosenVariation.share_type_name} ${getShareTypeVariationSizeLabel(chosenVariation.size ?? "")}`
                  : t("auth.registration.variation.selected")}
              </Text>
              {price != null && (
                <Text type="secondary">
                  {formatCurrency(Number(price))} /{" "}
                  {t("auth.registration.variation.per_delivery")}
                </Text>
              )}
              {data.default_delivery_station_day && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {t("auth.registration.variation.station_chosen")}
                </Text>
              )}
            </Space>
            <Button onClick={() => setModalOpen(true)}>
              {t("auth.registration.variation.change")}
            </Button>
          </Flex>
        </Card>
      ) : (
        <Button
          type="primary"
          size="large"
          onClick={() => setModalOpen(true)}
          style={{ marginBottom: 16 }}
        >
          {t("auth.registration.variation.choose")}
        </Button>
      )}

      <NewSubscriptionModal
        visible={modalOpen}
        mode="public"
        forceTrial={data.is_trial === true}
        subscriptions={[]}
        onIntent={handleIntent}
        onCancel={() => setModalOpen(false)}
        onSuccess={() => setModalOpen(false)}
      />

      {!chosenId && (
        <Alert
          type="info"
          showIcon
          message={t("auth.registration.variation.optional_hint")}
          style={{ marginBottom: 12 }}
        />
      )}

      <Flex justify="space-between" style={{ marginTop: 8 }}>
        <Button onClick={back}>{t("auth.registration.actions.back")}</Button>
        <Button type="primary" onClick={next}>
          {chosenId
            ? t("auth.registration.actions.next")
            : t("auth.registration.variation.skip")}
        </Button>
      </Flex>
    </>
  );
}
