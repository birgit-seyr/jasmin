import { Form } from "antd";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { commissioningShareDeliveryPartialUpdate } from "@shared/api/generated/commissioning/commissioning";
import type { ShareDelivery } from "@shared/api/generated/models";
import { notify } from '@shared/utils';

type DeliveryRecord = ShareDelivery;

/** The subset of writable ``ShareDelivery`` fields this modal patches. */
type ShareDeliveryPatch = Partial<
  Pick<
    ShareDelivery,
    | "delivery_station_day"
    | "joker_taken"
    | "donation_joker_taken"
    | "apply_to_future"
  >
>;

export const useModalMemberDeliveryEdit = () => {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [isVisible, setIsVisible] = useState(false);
  const [loading, setLoading] = useState(false);
  const [deliveryId, setDeliveryId] = useState<string | null>(null);
  const [currentDelivery, setCurrentDelivery] = useState<DeliveryRecord | null>(null);

  const openModal = useCallback(
    (delivery: DeliveryRecord) => {
      if (delivery) {
        setDeliveryId(delivery.id ?? null);
        setCurrentDelivery(delivery);
        form.setFieldsValue({
          delivery_station_day: delivery.delivery_station_day || undefined,
          joker_taken: delivery.joker_taken || false,
          donation_joker_taken: delivery.donation_joker_taken || false,
          apply_to_future: false,
        });
      }
      setIsVisible(true);
    },
    [form]
  );

  const closeModal = useCallback(() => {
    setIsVisible(false);
    form.resetFields();
    setDeliveryId(null);
    setCurrentDelivery(null);
  }, [form]);

  const saveDelivery = useCallback(
    async (onSuccess?: (values: Record<string, unknown>) => void) => {
      try {
        const values = await form.validateFields();
        setLoading(true);

        // ``joker_taken`` is undefined when the joker checkbox isn't
        // rendered (tenant has ``uses_jokers=false``). Dropping it
        // from the payload preserves whatever the row currently has,
        // instead of silently clearing it to false.
        const payload: ShareDeliveryPatch = {
          delivery_station_day: values.delivery_station_day,
          apply_to_future: values.apply_to_future || false,
        };
        if (values.joker_taken !== undefined) {
          payload.joker_taken = values.joker_taken;
        }
        if (values.donation_joker_taken !== undefined) {
          payload.donation_joker_taken = values.donation_joker_taken;
        }
        // Directional cast at the orval boundary: this is a PATCH with a
        // partial body, but the generated signature wants the full
        // NonReadonly<ShareDelivery> model.
        await commissioningShareDeliveryPartialUpdate(
          deliveryId!,
          payload as ShareDelivery,
        );

        notify.success(t("members.delivery_updated_successfully"));

        if (onSuccess) {
          onSuccess(values);
        }

        closeModal();
      } catch (error: unknown) {
        if (error && typeof error === 'object' && 'errorFields' in error) {
          console.error("Validation failed:", error);
        } else {
          console.error("Failed to update delivery:", error);
          notify.error(t("members.delivery_update_failed"));
        }
      } finally {
        setLoading(false);
      }
    },
    [form, deliveryId, closeModal, t]
  );

  return {
    isVisible,
    loading,
    form,
    currentDelivery,
    openModal,
    closeModal,
    saveDelivery,
    t,
  };
};
