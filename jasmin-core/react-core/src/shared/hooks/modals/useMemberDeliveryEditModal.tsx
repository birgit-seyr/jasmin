import { Form } from "antd";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { commissioningShareDeliveryPartialUpdate } from "@shared/api/generated/commissioning/commissioning";
import type { ShareDelivery } from "@shared/api/generated/models";
import { useModalMutation } from "@shared/modals/shared/useModalMutation";

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

export const useMemberDeliveryEditModal = () => {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [isVisible, setIsVisible] = useState(false);
  const { saving: loading, run } = useModalMutation();
  const [deliveryId, setDeliveryId] = useState<string | null>(null);
  const [currentDelivery, setCurrentDelivery] = useState<DeliveryRecord | null>(null);

  const openModal = useCallback(
    (delivery: DeliveryRecord) => {
      setDeliveryId(delivery.id ?? null);
      setCurrentDelivery(delivery);
      form.setFieldsValue({
        delivery_station_day: delivery.delivery_station_day || undefined,
        joker_taken: delivery.joker_taken || false,
        donation_joker_taken: delivery.donation_joker_taken || false,
        apply_to_future: false,
      });
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
      let values: Record<string, unknown>;
      try {
        values = await form.validateFields();
      } catch {
        // The form shows its own field errors.
        return;
      }
      // ``joker_taken`` is undefined when the joker checkbox isn't
      // rendered (tenant has ``uses_jokers=false``). Dropping it
      // from the payload preserves whatever the row currently has,
      // instead of silently clearing it to false.
      const payload: ShareDeliveryPatch = {
        delivery_station_day: values.delivery_station_day as string | undefined,
        apply_to_future: Boolean(values.apply_to_future),
      };
      if (values.joker_taken !== undefined) {
        payload.joker_taken = Boolean(values.joker_taken);
      }
      if (values.donation_joker_taken !== undefined) {
        payload.donation_joker_taken = Boolean(values.donation_joker_taken);
      }
      await run(
        // Directional cast at the orval boundary: this is a PATCH with a
        // partial body, but the generated signature wants the full
        // NonReadonly<ShareDelivery> model.
        () =>
          commissioningShareDeliveryPartialUpdate(
            deliveryId!,
            payload as ShareDelivery,
          ),
        {
          successMessage: t("members.delivery_updated_successfully"),
          errorMessage: t("members.delivery_update_failed"),
          onSuccess: () => {
            onSuccess?.(values);
            closeModal();
          },
        },
      );
    },
    [form, run, deliveryId, closeModal, t]
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
