import { Descriptions, InputNumber, Modal } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCurrency, useDateFormat, useVariationLabel } from "@hooks/index";
import type { AboRecord } from "@features/abos/pages/types";

interface OfferSpotModalProps {
  open: boolean;
  record: AboRecord | null;
  /** Current active price for the row's variation — the pre-fill suggestion.
   *  Falls back to the row's stored price when the variation carries none. */
  suggestedPrice: number | null;
  loading: boolean;
  onCancel: () => void;
  onConfirm: (price: number | null) => void;
}

/**
 * "Review & send offer" — the office confirms the details and, crucially, the
 * PRICE before notifying a waiting-list member. A waiting_list entry can be a year
 * old, so the price field is pre-filled with the variation's CURRENT active
 * price; the office can override it (e.g. to keep a loyalty price). The member
 * then sees exactly this price on their accept page.
 */
export function OfferSpotModal({
  open,
  record,
  suggestedPrice,
  loading,
  onCancel,
  onConfirm,
}: OfferSpotModalProps) {
  const { t } = useTranslation();
  const { currencySymbol } = useCurrency();
  const { formatDate } = useDateFormat();
  const variationLabel = useVariationLabel();
  const [price, setPrice] = useState<number | null>(null);

  // Re-seed the price each time the modal opens for a row: prefer the current
  // active price, else the row's stored (possibly stale) price.
  useEffect(() => {
    if (!open || !record) return;
    const stored =
      record.price_per_delivery != null
        ? Number(record.price_per_delivery)
        : null;
    setPrice(suggestedPrice ?? stored);
  }, [open, record, suggestedPrice]);

  const term =
    record?.valid_from && record?.valid_until
      ? `${formatDate(record.valid_from)} – ${formatDate(record.valid_until)}`
      : record?.valid_from
        ? formatDate(record.valid_from)
        : "";

  return (
    <Modal
      open={open}
      title={t("abos.offer_modal_title")}
      okText={t("abos.notify_member")}
      cancelText={t("common.cancel")}
      confirmLoading={loading}
      onOk={() => onConfirm(price)}
      onCancel={onCancel}
      destroyOnClose
    >
      <Descriptions column={1} size="small" bordered>
        <Descriptions.Item label={t("members.member")}>
          {record?.member_string}
        </Descriptions.Item>
        <Descriptions.Item label={t("members.share_type_variation")}>
          {variationLabel(record?.share_type_variation_string)}
        </Descriptions.Item>
        <Descriptions.Item label={t("members.default_delivery_station")}>
          {record?.default_delivery_station_day_string}
        </Descriptions.Item>
        {term ? (
          <Descriptions.Item label={t("abos.offer_page.start")}>
            {term}
          </Descriptions.Item>
        ) : null}
        <Descriptions.Item label={t("members.quantity")}>
          {record?.quantity}
        </Descriptions.Item>
        <Descriptions.Item label={t("abos.price_per_delivery")}>
          <InputNumber
            // Descriptions.Item's label isn't programmatically tied to the
            // control — give the input its own accessible name.
            aria-label={t("abos.price_per_delivery")}
            value={price}
            onChange={(v) => setPrice(v)}
            min={0}
            step={0.5}
            precision={2}
            addonBefore={currencySymbol}
            style={{ width: "12em" }}
          />
        </Descriptions.Item>
      </Descriptions>
    </Modal>
  );
}
