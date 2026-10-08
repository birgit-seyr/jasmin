import { useQueryClient } from "@tanstack/react-query";
import { Form, Typography } from "antd";
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
import NumberInput from "@shared/ui/NumberInput";

const { Paragraph } = Typography;

// Billing reads the first non-zero of these, in this order, so a station is
// paid in one way only.
const FEE_FIELDS = [
  "fee_per_box_net",
  "fee_per_month_net",
  "fee_per_year_net",
] as const;

const isFee = (value: unknown) => Number(value ?? 0) > 0;

interface DeliveryStationFeeModalProps {
  open: boolean;
  deliveryStation: DeliveryStation | null;
  onClose: () => void;
  onSaved: () => void;
}

/**
 * Per-row modal for the pickup-station fees the farm owes a station. NET,
 * either/or: at most one of per-box / per-month / per-year applies (the other
 * two stay 0). Fees are Decimal-as-string on the wire, so the number fields'
 * values are coerced to String before the partial update. Mirrors
 * ResellerInvoiceSettingsModal.
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
            fee_per_box_net: deliveryStation.fee_per_box_net,
            fee_per_month_net: deliveryStation.fee_per_month_net,
            fee_per_year_net: deliveryStation.fee_per_year_net,
          }
        : null,
    [deliveryStation],
  );

  if (!deliveryStation) return null;

  const handleSubmit = (values: Record<string, unknown>) =>
    run(
      async () => {
        // Money fields are Decimal-as-string on the wire; NumberInput yields a
        // number → coerce back to String so the server DecimalField keeps cents.
        // A cleared field means no fee, which the server stores as 0: it
        // refuses null.
        const payload: Record<string, unknown> = { ...values };
        for (const key of FEE_FIELDS) {
          const value = payload[key];
          if (value === null || value === undefined || value === "") {
            payload[key] = "0";
          } else if (typeof value === "number") {
            payload[key] = String(value);
          }
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
      {FEE_FIELDS.map((name) => (
        <Form.Item
          key={name}
          name={name}
          label={t(`delivery_stations.${name}`)}
          dependencies={FEE_FIELDS.filter((other) => other !== name)}
          rules={[
            ({ getFieldValue }) => ({
              validator: (_, value) =>
                isFee(value) &&
                FEE_FIELDS.some(
                  (other) => other !== name && isFee(getFieldValue(other)),
                )
                  ? Promise.reject(new Error(t("delivery_stations.fee_only_one")))
                  : Promise.resolve(),
            }),
          ]}
        >
          <NumberInput
            min={0}
            step={0.01}
            suffix={currencySymbol}
            className="w-full"
          />
        </Form.Item>
      ))}
    </EditFormModal>
  );
};

export default DeliveryStationFeeModal;
