import { useQueryClient } from "@tanstack/react-query";
import { Form, InputNumber, Modal, Typography } from "antd";
import type { FC } from "react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useCurrency } from "@hooks/index";
import {
  commissioningDeliveryStationsPartialUpdate,
  getCommissioningDeliveryStationsListQueryKey,
} from "@shared/api/generated/commissioning/commissioning";
import type { DeliveryStation } from "@shared/api/generated/models";
import { ModalCancelSaveFooter } from "@shared/modals/shared";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";

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
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  const invalidateStations = useCallback(
    () =>
      queryClient.invalidateQueries({
        queryKey: getCommissioningDeliveryStationsListQueryKey(),
      }),
    [queryClient],
  );

  // fees_billing_period stores the raw PaymentCycle ENUM value (not a PK), so
  // build options straight from the enum; labels reuse the configuration ns.
  // const billingPeriodOptions = useMemo(
  //   () =>
  //     Object.values(PaymentCycleEnum).map((value) => ({
  //       value,
  //       label: t(`configuration.payment_cycle_${value.toLowerCase()}`),
  //     })),
  //   [t],
  // );

  useEffect(() => {
    if (open && deliveryStation) {
      form.setFieldsValue({
        fee_per_box_net: deliveryStation.fee_per_box_net ?? "0",
        fee_per_month_net: deliveryStation.fee_per_month_net ?? "0",
        fee_per_year_net: deliveryStation.fee_per_year_net ?? "0",
        fees_billing_period: deliveryStation.fees_billing_period ?? null,
      });
    }
  }, [open, deliveryStation, form]);

  if (!deliveryStation) return null;

  const handleSave = async () => {
    const values = await form.validateFields();
    const id = String(deliveryStation.id ?? "");
    if (!id) return;
    setSaving(true);
    try {
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
        id,
        payload as unknown as DeliveryStation,
      );
      await invalidateStations();
      notify.success(t("delivery_stations.fee_saved"));
      onSaved();
      onClose();
    } catch (error) {
      notify.error(
        getErrorMessage(error, t("delivery_stations.fee_save_error")),
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      width={520}
      destroyOnHidden
      title={`${t("delivery_stations.fee_title")} — ${deliveryStation.short_name ?? ""}`}
      footer={
        <ModalCancelSaveFooter
          onCancel={onClose}
          onPrimary={handleSave}
          loading={saving}
        />
      }
    >
      <Paragraph type="secondary">{t("delivery_stations.fee_intro")}</Paragraph>
      <Form form={form} layout="vertical" requiredMark={false}>
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
        </Form.Item> */}
        {/* <Form.Item
          name="fees_billing_period"
          label={t("delivery_stations.fees_billing_period")}
        >
          <Select
            allowClear
            options={billingPeriodOptions}
            placeholder={t("delivery_stations.fees_billing_period_placeholder")}
          />
        </Form.Item> */}
      </Form>
    </Modal>
  );
};

export default DeliveryStationFeeModal;
