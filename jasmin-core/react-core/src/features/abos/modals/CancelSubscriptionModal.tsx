import { StopOutlined } from "@ant-design/icons";
import { Alert, DatePicker, Form, Input, Modal, Space, Typography } from "antd";
import dayjs from "dayjs";
import type { Dayjs } from "dayjs";
import { useDateFormat, useVariationLabel } from "@hooks/index";
import type { FC } from "react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { commissioningAbosCancelCreate } from "@shared/api/generated/commissioning/commissioning";
import { notify, toApiDate } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import { getNextSunday } from "@shared/utils/nextSunday";
import { ModalCancelSaveFooter } from "@shared/modals/shared";
import type { AboRecord } from "@features/abos/pages/types";

const { Title, Paragraph, Text } = Typography;

interface CancelSubscriptionModalProps {
  isOpen: boolean;
  onClose: () => void;
  abo: AboRecord | null;
  /** Fires after the API call succeeds so the parent can refetch /
   *  refresh the row. The modal closes itself on success. */
  onCancelled: () => void;
}

/**
 * Modal that drives the subscription cancellation flow. Captures the
 * legally-effective end date + optional reason and routes through the
 * ``POST /api/commissioning/abos/{id}/cancel/`` action — NOT a plain
 * PATCH. Going through the action endpoint is what triggers the
 * service-layer side effects:
 *
 *   * stamps ``cancelled_at`` / ``cancelled_by`` / ``cancelled_effective_at``
 *   * truncates ``valid_until`` to the effective date
 *   * deletes ShareDeliveries past the new end
 *   * drops PLANNED ChargeSchedule rows past the new end
 *     (ISSUED/PAID/FAILED/WAIVED preserved — already-billed money stays
 *     billed)
 *   * fires ``recompute_shares`` for the affected weeks
 *
 * Bypassing this via inline-edit would skip every one of those — see
 * the server-side lockdown in ``SubscriptionSerializer.Meta.read_only_fields``
 * and ``test_subscription_serializer_locks.py``.
 */
export const CancelSubscriptionModal: FC<CancelSubscriptionModalProps> = ({
  isOpen,
  onClose,
  abo,
  onCancelled,
}) => {
  const { t } = useTranslation();
  const { dateFormat, formatDate } = useDateFormat();
  const variationLabel = useVariationLabel();
  const [effectiveAt, setEffectiveAt] = useState<Dayjs | null>(null);
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(false);

  // ``next Sunday on or after today`` — the earliest the cancellation
  // can take effect. Sundays are required because ``valid_until``
  // (which we truncate to ``effective_at`` server-side) must fall on a
  // Sunday by the model-level rule in ``TimeBoundMixin``.
  const nextSunday = getNextSunday();

  // Reset state every time the modal opens for a different row, so
  // the previous row's reason / date never leaks across.
  //
  // The date deliberately starts empty — making the user pick a date
  // is a small friction that prevents accidental cancellations from
  // a quick double-click on the per-row Cancel button. The picker's
  // ``disabledDate`` still constrains the choice to valid Sundays
  // inside ``[next_sunday, valid_until]``.
  useEffect(() => {
    if (isOpen) {
      setEffectiveAt(null);
      setReason("");
    }
  }, [isOpen, abo?.id]);

  if (!abo) return null;

  const validFrom = abo.valid_from ? dayjs(abo.valid_from) : null;
  const validUntil = abo.valid_until ? dayjs(abo.valid_until) : null;

  const handleSubmit = async () => {
    if (!abo.id || !effectiveAt) return;
    // Mirror the server-side validation client-side so the user gets
    // an immediate notify instead of a 400 round-trip.
    if (effectiveAt.day() !== 0) {
      notify.error(
        t("members.cancel_abo_must_be_sunday"),
      );
      return;
    }
    if (effectiveAt.isBefore(nextSunday, "day")) {
      notify.error(
        t("members.cancel_abo_before_next_sunday"),
      );
      return;
    }
    if (validFrom && effectiveAt.isBefore(validFrom, "day")) {
      notify.error(
        t("members.cancel_abo_effective_before_start"),
      );
      return;
    }
    if (validUntil && effectiveAt.isAfter(validUntil, "day")) {
      notify.error(
        t("members.cancel_abo_effective_after_end"),
      );
      return;
    }

    setLoading(true);
    try {
      await commissioningAbosCancelCreate(String(abo.id), {
        effective_at: toApiDate(effectiveAt)!,
        reason: reason.trim() || undefined,
      });
      notify.success(
        t("members.cancel_abo_success"),
      );
      onCancelled();
      onClose();
    } catch (err) {
      // Surface the backend's specific reason (getErrorMessage reads the Jasmin
      // {code, message} body); the i18n key is only the fallback.
      notify.error(getErrorMessage(err, t("members.cancel_abo_error")));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title={t("members.cancel_abo_modal_title")}
      open={isOpen}
      onCancel={onClose}
      footer={
        <ModalCancelSaveFooter
          onCancel={onClose}
          onPrimary={handleSubmit}
          loading={loading}
          primaryDanger
          primaryIcon={<StopOutlined />}
          primaryLabel={t("members.cancel_abo_primary")}
        />
      }
      width={560}
      destroyOnHidden
    >
      <Space direction="vertical" size="middle" className="w-full">
        <Title level={5} style={{ margin: 0 }}>
          {abo.member_first_name} {abo.member_last_name}
          {abo.share_type_variation_string
            ? ` — ${variationLabel(abo.share_type_variation_string)}`
            : ""}
        </Title>

        {(validFrom || validUntil) && (
          <Text type="secondary" style={{ fontSize: 13 }}>
            {validFrom && (
              <>
                {t("members.valid_from")}:{" "}
                {formatDate(validFrom)}
              </>
            )}
            {validFrom && validUntil && " — "}
            {validUntil && (
              <>
                {t("members.valid_until")}:{" "}
                {formatDate(validUntil)}
              </>
            )}
          </Text>
        )}

        <Alert
          type="warning"
          showIcon
          message={t("members.cancel_abo_warning_title")}
          description={
            <ul style={{ marginBottom: 0, paddingLeft: 20 }}>
              <li>
                {t("members.cancel_abo_warning_deliveries")}
              </li>
              <li>
                {t("members.cancel_abo_warning_charges")}
              </li>
            </ul>
          }
        />

        <Form layout="vertical" disabled={loading}>
          <Form.Item
            label={t("members.cancel_abo_effective_at")}
            required
          >
            <DatePicker
              value={effectiveAt}
              onChange={setEffectiveAt}
              format={dateFormat}
              style={{ width: "100%" }}
              aria-label={t("members.cancel_abo_effective_at")}
              aria-required
              disabledDate={(d) => {
                // Sunday-only (dayjs: 0 = Sunday). The model rule on
                // ``valid_until`` (``TimeBoundMixin``) forces this.
                if (d.day() !== 0) return true;
                // Never past — earliest is the next Sunday on or after
                // today. Cancellation in the past is nonsense.
                if (d.isBefore(nextSunday, "day")) return true;
                // Don't allow extending the term — effective_at must
                // sit inside the subscription's natural window.
                if (validFrom && d.isBefore(validFrom, "day")) return true;
                if (validUntil && d.isAfter(validUntil, "day")) return true;
                return false;
              }}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t("members.cancel_abo_effective_at_hint")}
            </Text>
          </Form.Item>
          <Form.Item
            label={t("members.cancel_abo_reason_label")}
          >
            <Input.TextArea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              aria-label={t("members.cancel_abo_reason_label")}
              rows={3}
              maxLength={1000}
              showCount
              placeholder={t("members.cancel_abo_reason_placeholder")}
            />
          </Form.Item>
        </Form>

        <Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 12 }}>
          {t("members.cancel_abo_footnote")}
        </Paragraph>
      </Space>
    </Modal>
  );
};
