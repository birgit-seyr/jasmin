import { useQueryClient } from "@tanstack/react-query";
import { Form, InputNumber, Typography } from "antd";
import type { FC } from "react";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { useCurrency } from "@hooks/index";
import {
  commissioningDeliveryStationsPartialUpdate,
  getCommissioningDeliveryStationsListQueryKey,
} from "@shared/api/generated/commissioning/commissioning";
import type { DeliveryStation } from "@shared/api/generated/models";
import { EditFormModal, useModalMutation } from "@shared/modals/shared";

const { Paragraph } = Typography;

interface DeliveryStationFeeModalProps {
  open: boolean;
  deliveryStation: DeliveryStation | null;
  onClose: () => void;
  onSaved: () => void;
}

/**
 * Per-row modal for the pickup-station fees the solawi owes a station. NET,
 * either/or: at most one of per-box / per-month / per-year applies (the other
 * two stay 0). fees_billing_period is the billing cadence. Fees are
 * Decimal-as-string on the wire, so InputNumber values are coerced to String
 * before the partial update. Mirrors ResellerInvoiceSettingsModal.
 */
export const DeliveryStationFeeModal: FC<DeliveryStationFeeModalProps> = ({
  open,
  deliveryStation,
  onClose,
  onSaved,
}) => {
  const { t } = useTranslation();
  const { currencySymbol } = useCurrency();
  const queryClient = useQueryClient();
  const { saving, run } = useModalMutation();

  const invalidateStations = useCallback(
    () =>
      queryClient.invalidateQueries({
        queryKey: getCommissioningDeliveryStationsListQueryKey(),
      }),
    [queryClient],
  );

  const initialValues = useMemo<Record<string, unknown> | null>(
    () =>
      deliveryStation
        ? {
            fee_per_box_net: deliveryStation.fee_per_box_net ?? "0",
            fee_per_month_net: deliveryStation.fee_per_month_net ?? "0",
            fee_per_year_net: deliveryStation.fee_per_year_net ?? "0",
            fees_billing_period: deliveryStation.fees_billing_period ?? null,
          }
        : null,
    [deliveryStation],
  );

  if (!deliveryStation) return null;

  const handleSubmit = (values: Record<string, unknown>) =>
    run(
      async () => {
        // Money fields are Decimal-as-string on the wire; InputNumber yields a
        // number → coerce back to String so the server DecimalField keeps cents.
        const payload: Record<string, unknown> = { ...values };
        for (const key of [
          "fee_per_box_net",
          "fee_per_month_net",
          "fee_per_year_net",
        ]) {
          if (typeof payload[key] === "number")
            payload[key] = String(payload[key]);
        }
        await commissioningDeliveryStationsPartialUpdate(
          String(deliveryStation.id ?? ""),
          payload as unknown as DeliveryStation,
        );
        await invalidateStations();
      },
      {
        successMessage: t("delivery_stations.fee_saved"),
        errorMessage: t("delivery_stations.fee_save_error"),
        onSuccess: () => {
          onSaved();
          onClose();
        },
      },
    );

  return (
    <EditFormModal
      open={open}
      width={520}
      title={`${t("delivery_stations.fee_title")} — ${deliveryStation.short_name ?? ""}`}
      description={
        <Paragraph type="secondary">
          {t("delivery_stations.fee_intro")}
        </Paragraph>
      }
      initialValues={initialValues}
      onSubmit={handleSubmit}
      onCancel={onClose}
      loading={saving}
      requiredMark={false}
    >
      <Form.Item
        name="fee_per_box_net"
        label={t("delivery_stations.fee_per_box_net")}
      >
        <InputNumber
          min={0}
          step={0.01}
          suffix={currencySymbol}
          style={{ width: "100%" }}
        />
      </Form.Item>
      {/* <Form.Item
        name="fee_per_month_net"
        label={t("delivery_stations.fee_per_month_net")}
      >
        <InputNumber
          min={0}
          step={0.01}
          suffix={currencySymbol}
          style={{ width: "100%" }}
        />
      </Form.Item>
      <Form.Item
        name="fee_per_year_net"
        label={t("delivery_stations.fee_per_year_net")}
      >
        <InputNumber
          min={0}
          step={0.01}
          suffix={currencySymbol}
          style={{ width: "100%" }}
        />
      </Form.Item>
      <Form.Item
        name="fees_billing_period"
        label={t("delivery_stations.fees_billing_period")}
      >
        <Select
          allowClear
          options={billingPeriodOptions}
          placeholder={t("delivery_stations.fees_billing_period_placeholder")}
        />
      </Form.Item> */}
    </EditFormModal>
  );
};

export default DeliveryStationFeeModal;
