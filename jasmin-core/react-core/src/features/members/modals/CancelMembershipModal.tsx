import { StopOutlined } from "@ant-design/icons";
import {
  Alert,
  Checkbox,
  DatePicker,
  Form,
  Input,
  Modal,
  Space,
  Typography,
} from "antd";
import type { Dayjs } from "dayjs";
import type { FC } from "react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  commissioningMembersCancelCreate,
  commissioningMyMembershipCancelCreate,
} from "@shared/api/generated/commissioning/commissioning";
import { notify, toApiDate } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import { ModalCancelSaveFooter } from "@shared/modals/shared";
import { useDateFormat } from "@hooks/index";

const { Title, Paragraph, Text } = Typography;

interface CancelMembershipModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** Office-cancel: the member to cancel. Ignored when ``self`` is set. */
  memberId?: string | null;
  /** Shown in the title (office mode). */
  memberName?: string;
  /** Member self-service: post to the token-scoped endpoint instead of the
   *  office one (the caller can only ever cancel their own membership). */
  self?: boolean;
  /** Fires after the API call succeeds so the parent can refetch. The modal
   *  closes itself on success. */
  onCancelled: () => void;
}

/**
 * Drives membership cancellation through the dedicated action endpoints —
 * NOT a plain PATCH. Going through the action is what triggers the
 * service-layer side effects in ``cancel_member_with_coop_shares``:
 *
 *   * stamps ``cancelled_at`` / ``cancelled_by`` / ``cancelled_effective_at``
 *     (+ the free-text reason) on the member
 *   * cascades to every open ``CoopShare`` — they're marked cancelled and get
 *     a ``payback_due_date`` snapshotted to ``effective + retention months``
 *     (the equity stays in the cooperative until then)
 *   * ends the member's still-active subscriptions
 *
 * Both modes REFUSE while the member still holds active subscriptions. Member
 * self-service (``self`` → ``my_membership/cancel/``) has no override. The
 * office path (``memberId`` → ``members/{id}/cancel/``) exposes a ``force``
 * checkbox: ticking it cancels anyway and ends the active subscriptions in the
 * same transaction (for e.g. a deceased member). The office response lists any
 * subscription that could not be ended (it keeps a live mandate).
 */
export const CancelMembershipModal: FC<CancelMembershipModalProps> = ({
  isOpen,
  onClose,
  memberId,
  memberName,
  self = false,
  onCancelled,
}) => {
  const { t } = useTranslation();
  const { dateFormat } = useDateFormat();
  const [effectiveAt, setEffectiveAt] = useState<Dayjs | null>(null);
  const [reason, setReason] = useState("");
  const [force, setForce] = useState(false);
  const [loading, setLoading] = useState(false);

  // Start empty every open — picking a date is friction that guards against an
  // accidental cancellation from a stray click on the per-row button.
  useEffect(() => {
    if (isOpen) {
      setEffectiveAt(null);
      setReason("");
      setForce(false);
    }
  }, [isOpen, memberId, self]);

  const handleSubmit = async () => {
    if (!effectiveAt) {
      notify.error(t("members.cancel_membership_effective_required"));
      return;
    }
    if (!self && !memberId) return;

    setLoading(true);
    try {
      if (self) {
        await commissioningMyMembershipCancelCreate({
          effective_at: toApiDate(effectiveAt)!,
          reason: reason.trim() || undefined,
        });
      } else {
        const result = await commissioningMembersCancelCreate(
          String(memberId),
          {
            effective_at: toApiDate(effectiveAt)!,
            reason: reason.trim() || undefined,
            force,
          },
        );
        const notEnded = result?.subscriptions_not_ended ?? [];
        if (notEnded.length > 0) {
          notify.warning(
            t("members.cancel_membership_partial_warning", {
              count: notEnded.length,
            }),
          );
        }
      }
      notify.success(t("members.cancel_membership_success"));
      onCancelled();
      onClose();
    } catch (err) {
      // Office path: the backend REFUSES (400) while active subscriptions
      // remain. Surface a clear "tick force" hint rather than the generic error.
      const code = (err as { response?: { data?: { code?: string } } })
        ?.response?.data?.code;
      if (!self && code === "member.has_active_subscriptions") {
        notify.error(t("members.cancel_membership_active_subs_error"));
      } else {
        notify.error(
          getErrorMessage(err, t("members.cancel_membership_error")),
        );
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title={t("members.cancel_membership_modal_title")}
      open={isOpen}
      onCancel={onClose}
      footer={
        <ModalCancelSaveFooter
          onCancel={onClose}
          onPrimary={handleSubmit}
          loading={loading}
          primaryDanger
          primaryIcon={<StopOutlined />}
          primaryLabel={t("members.cancel_membership_primary")}
        />
      }
      width={560}
      destroyOnHidden
    >
      <Space direction="vertical" size="middle" className="w-full">
        {!self && memberName && (
          <Title level={5} style={{ margin: 0 }}>
            {memberName}
          </Title>
        )}

        <Alert
          type="warning"
          showIcon
          message={t("members.cancel_membership_warning_title")}
          description={
            <ul style={{ marginBottom: 0, paddingLeft: 20 }}>
              {self ? (
                <li>{t("members.cancel_membership_restraint")}</li>
              ) : (
                <li>{t("members.cancel_membership_warning_subs")}</li>
              )}
              <li>{t("members.cancel_membership_warning_coop")}</li>
            </ul>
          }
        />

        <Form layout="vertical" disabled={loading}>
          <Form.Item
            label={t("members.cancel_membership_effective_at")}
            required
          >
            <DatePicker
              value={effectiveAt}
              onChange={setEffectiveAt}
              format={dateFormat}
              style={{ width: "100%" }}
              aria-label={t("members.cancel_membership_effective_at")}
              aria-required
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t("members.cancel_membership_effective_at_hint")}
            </Text>
          </Form.Item>
          <Form.Item label={t("members.cancel_membership_reason_label")}>
            <Input.TextArea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              aria-label={t("members.cancel_membership_reason_label")}
              rows={3}
              maxLength={1000}
              showCount
              placeholder={t("members.cancel_membership_reason_placeholder")}
            />
          </Form.Item>
          {!self && (
            <Form.Item style={{ marginBottom: 0 }}>
              <Checkbox
                checked={force}
                onChange={(e) => setForce(e.target.checked)}
              >
                {t("members.cancel_membership_force")}
              </Checkbox>
              <Text type="secondary" style={{ display: "block", fontSize: 12 }}>
                {t("members.cancel_membership_force_hint")}
              </Text>
            </Form.Item>
          )}
        </Form>

        <Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 12 }}>
          {t("members.cancel_membership_footnote")}
        </Paragraph>
      </Space>
    </Modal>
  );
};
