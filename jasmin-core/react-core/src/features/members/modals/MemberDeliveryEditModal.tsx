import { Button, Checkbox, Form, Modal, Select, Space } from "antd";
import dayjs from "dayjs";
import { toApiDate } from "@shared/utils";
import { FC, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  useDeliveryStationDays,
  useModalMemberDeliveryEdit,
  useTenant,
} from "@hooks/index";
import { useEnterToSubmit } from "@shared/modals/shared";
import type { ShareDelivery } from "@shared/api/generated/models";

interface MemberDeliveryEditModalProps {
  visible: boolean;
  onCancel: () => void;
  onSuccess: () => void;
  delivery: ShareDelivery | null;
}

const MemberDeliveryEditModal: FC<MemberDeliveryEditModalProps> = ({
  visible,
  onCancel,
  onSuccess,
  delivery,
}) => {
  const { t } = useTranslation();
  const { getSetting } = useTenant();
  const usesJokers = getSetting("uses_jokers", true);
  const usesDonationJokers = getSetting("uses_donation_jokers", false);
  const { form, isVisible, loading, currentDelivery, openModal, closeModal, saveDelivery } =
    useModalMemberDeliveryEdit();

  // Compute the delivery date from year + week + day_number to filter active DSDs
  const deliveryDate = useMemo(() => {
    if (!delivery?.year || !delivery?.delivery_week) return undefined;
    const d = dayjs()
      .year(delivery.year)
      .isoWeek(delivery.delivery_week)
      .startOf("isoWeek")
      .add(delivery.delivery_day_number ?? 0, "day");
    return toApiDate(d)!;
  }, [delivery?.year, delivery?.delivery_week, delivery?.delivery_day_number]);

  // Pass the delivery's own year/week so ``capacity_by_week`` is keyed for
  // exactly the week we look up below (``num_weeks: 1``). Without this the
  // window defaults to the current week and the lookup misses → capacity
  // filtering silently no-ops.
  const dsdParams = useMemo<{
    active_at_date?: string;
    year?: number;
    delivery_week?: number;
    num_weeks?: number;
  }>(() => {
    const params: {
      active_at_date?: string;
      year?: number;
      delivery_week?: number;
      num_weeks?: number;
    } = {};
    if (deliveryDate) params.active_at_date = deliveryDate;
    if (delivery?.year && delivery?.delivery_week) {
      params.year = delivery.year;
      params.delivery_week = delivery.delivery_week;
      params.num_weeks = 1;
    }
    return params;
  }, [deliveryDate, delivery?.year, delivery?.delivery_week]);

  const { deliveryStationDays, loading: dsdLoading } =
    useDeliveryStationDays(dsdParams);

  // Build week key for capacity lookup
  const weekKey = delivery?.year && delivery?.delivery_week
    ? `${delivery.year}-${delivery.delivery_week}`
    : undefined;

  // Show every active station-day for the week — across ALL weekdays, not just
  // the delivery's current day — so a delivery can be moved to a different day
  // (the backend re-points its Share to that day). Each label carries the
  // weekday, and full ones are greyed out (disabled) below rather than hidden.
  const filteredOptions = deliveryStationDays;

  // Build select options, with a fallback for the current value while loading
  const selectOptions = useMemo(() => {
    const mapped = filteredOptions.map((dsd) => {
      const cap = weekKey ? dsd.capacity_by_week?.[weekKey] : undefined;
      const isFull = cap != null && cap.free !== null && cap.free <= 0;
      return {
        value: dsd.value,
        label: dsd.label,
        free: cap?.free,
        // Grey out full station-days — but never the one already assigned.
        disabled: isFull && dsd.value !== delivery?.delivery_station_day,
      };
    });
    // If loading and current value isn't in options yet, add a placeholder option
    if (dsdLoading && delivery?.delivery_station_day && !mapped.some((o) => o.value === delivery.delivery_station_day)) {
      mapped.unshift({
        value: delivery.delivery_station_day,
        label: delivery.delivery_station_name ?? t("common.loading"),
        free: undefined,
        disabled: false,
      });
    }
    return mapped;
  }, [filteredOptions, dsdLoading, delivery?.delivery_station_day, delivery?.delivery_station_name, weekKey, t]);

  const stationChanged = Form.useWatch("delivery_station_day", form) !== currentDelivery?.delivery_station_day;

  useEffect(() => {
    if (visible && delivery && !isVisible) {
      openModal(delivery);
    } else if (!visible && isVisible) {
      closeModal();
    }
  }, [visible, delivery, isVisible, openModal, closeModal]);

  const handleSave = () => {
    saveDelivery(() => {
      if (onSuccess) onSuccess();
      if (onCancel) onCancel();
    });
  };

  const handleCancel = () => {
    closeModal();
    if (onCancel) onCancel();
  };

  const handleKeyDown = useEnterToSubmit(handleSave);

  return (
    <Modal
      title={t("members.edit_delivery")}
      open={isVisible}
      onCancel={handleCancel}
      footer={
        <Space>
          <Button onClick={handleCancel}>{t("common.cancel")}</Button>
          <Button type="primary" onClick={handleSave} loading={loading}>
            {t("common.save")}
          </Button>
        </Space>
      }
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        onKeyDown={handleKeyDown}
        onValuesChange={(changed) => {
          // A delivery is either skipped (joker) or donated (donation
          // joker), never both — checking one clears the other.
          if (changed.joker_taken === true) {
            form.setFieldValue("donation_joker_taken", false);
          }
          if (changed.donation_joker_taken === true) {
            form.setFieldValue("joker_taken", false);
          }
        }}
      >
        <Form.Item
          name="delivery_station_day"
          label={t("delivery.station")}
        >
          <Select
            loading={dsdLoading}
            options={selectOptions}
            optionRender={(option) => (
              <div>
                <div>{option.label}</div>
                {option.data.free != null && (
                  <div style={{ fontSize: "0.75em", color: "darkgreen" }}>
                    {t("delivery.free_spots_remaining", {
                      count: option.data.free as number,
                    })}
                  </div>
                )}
              </div>
            )}
            placeholder={t("delivery.select_station")}
          />
        </Form.Item>
        {stationChanged && (
          <Form.Item name="apply_to_future" valuePropName="checked">
            <Checkbox>{t("members.apply_station_to_future")}</Checkbox>
          </Form.Item>
        )}
        {usesJokers && (delivery?.amount_of_jokers ?? 0) > 0 && (
          <Form.Item name="joker_taken" valuePropName="checked">
            <Checkbox>{t("delivery.joker_taken")}</Checkbox>
          </Form.Item>
        )}
        {usesDonationJokers &&
          (delivery?.amount_of_donation_jokers ?? 0) > 0 && (
            <Form.Item name="donation_joker_taken" valuePropName="checked">
              <Checkbox>{t("delivery.donation_joker_taken")}</Checkbox>
            </Form.Item>
          )}
      </Form>
    </Modal>
  );
};

export default MemberDeliveryEditModal;
