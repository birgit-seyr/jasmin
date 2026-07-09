import { useCallback, useMemo } from "react";
import type { FC } from "react";
import { Checkbox, Descriptions, Modal, Tag } from "antd";
import { usePaperReceivedToggle } from "@hooks/usePaperReceivedToggle";
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { unwrapList } from "@shared/utils";
import { parseDateLoose } from "@shared/utils/endOfTerm";
import { useDateFormat } from "@hooks/configuration/useDateFormat";
import { useTimeFormat } from "@hooks/configuration/useTimeFormat";
import { useCurrency } from "@hooks/configuration/useCurrency";
import { useTenant, useVariationLabel } from "@hooks/index";
import {
  getPaymentsBillingProfilesListQueryKey,
  usePaymentsBillingProfilesList,
  usePaymentsBillingProfilesPartialUpdate,
} from "@shared/api/generated/payments-—-billing-profiles/payments-—-billing-profiles";
import type { BillingProfile } from "@shared/api/generated/models";
import {
  adminConfirmationAuditItems,
  getAdminConfirmationStatus,
  ModalStatusBanner,
  adminConfirmationFooter,
} from "@shared/modals/shared";
import type { AboRecord } from "@features/abos/pages/types";

interface AdminConfirmationModalAbosProps {
  isOpen: boolean;
  onClose: () => void;
  abo: AboRecord | null;
  onConfirm?: () => void;
  /**
   * Optional handler that closes this modal and opens the
   * RejectAboModal for the same subscription. When provided, a
   * destructive "Reject" button appears between Cancel and Confirm
   * for pending rows.
   */
  onReject?: () => void;
  loading?: boolean;
}

export const AdminConfirmationModalAbos: FC<
  AdminConfirmationModalAbosProps
> = ({ isOpen, onClose, abo, onConfirm, onReject, loading = false }) => {
  const { t } = useTranslation();
  const { dateFormat, formatDate, formatDateWithFallback } = useDateFormat();
  const variationLabel = useVariationLabel();
  const { formatDateTime } = useTimeFormat();
  const { formatCurrency } = useCurrency();
  const queryClient = useQueryClient();
  const { getSetting } = useTenant();
  const requiresSepaPaper = Boolean(
    getSetting("requires_paper_signature_for_sepa_mandate", false),
  );

  // SEPA mandate status for the abo's member — confirming an abo for a member
  // without a usable mandate is a red flag the office should see right here.
  const { data: profiles } = usePaymentsBillingProfilesList(
    { member: abo?.member },
    { query: { enabled: isOpen && !!abo?.member } },
  );
  const billingProfile = useMemo<BillingProfile | undefined>(() => {
    // Server filters to this member (one profile per member), so take the first.
    return unwrapList<BillingProfile>(profiles)[0];
  }, [profiles]);
  const hasActiveMandate = Boolean(billingProfile?.is_sepa_ready);

  const patchProfile = usePaymentsBillingProfilesPartialUpdate();
  const { paperReceived, handlePaperToggle } = usePaperReceivedToggle({
    initialValue: Boolean(billingProfile?.sepa_mandate_paper_received_at),
    id: billingProfile?.id,
    patch: (id, value) =>
      patchProfile.mutateAsync({
        id,
        data: { sepa_mandate_paper_received_at: value } as BillingProfile,
      }),
    onPatched: () =>
      void queryClient.invalidateQueries({
        queryKey: getPaymentsBillingProfilesListQueryKey(),
      }),
  });

  const calculateDeliveryDays = useCallback(
    (record: AboRecord | null) => {
      if (
        !record ||
        !record.valid_from ||
        !record.valid_until ||
        record.delivery_day_number === undefined
      ) {
        return null;
      }

      try {
        const startDate = parseDateLoose(record.valid_from, dateFormat);
        const endDate = parseDateLoose(record.valid_until, dateFormat);

        if (!startDate || !endDate) {
          return null;
        }

        if (endDate.isBefore(startDate)) {
          return 0;
        }

        const deliveryDayNumber = Number(record.delivery_day_number);
        const targetWeekday =
          deliveryDayNumber === 6 ? 0 : deliveryDayNumber + 1;

        let deliveryCount = 0;
        let currentDate = startDate.clone();

        while (
          currentDate.day() !== targetWeekday &&
          (currentDate.isBefore(endDate) || currentDate.isSame(endDate))
        ) {
          currentDate = currentDate.add(1, "day");
        }

        while (currentDate.isBefore(endDate)) {
          deliveryCount++;
          currentDate = currentDate.add(7, "days");
        }

        return deliveryCount;
      } catch (error) {
        console.error("Error calculating delivery days:", error);
        return null;
      }
    },
    [dateFormat],
  );

  if (!abo) {
    return null;
  }

  const aboStatus = getAdminConfirmationStatus(abo, t);
  const deliveries = calculateDeliveryDays(abo);
  const isRejected = !!abo.admin_rejected_at;

  return (
    <Modal
      title={
        isRejected
          ? t("members.rejected_modal_title")
          : t("members.admin_confirmation_title")
      }
      open={isOpen}
      onCancel={onClose}
      footer={adminConfirmationFooter({
        isTerminal: abo.admin_confirmed || isRejected,
        onClose,
        onConfirm,
        confirmLabel: t("members.confirm_abo"),
        cancelLabel: t("common.cancel"),
        loading,
        onReject,
        rejectLabel: t("members.reject_member"),
      })}
      width={600}
      destroyOnHidden
    >
      <div style={{ padding: "20px 0" }}>
        {isRejected && (
          <ModalStatusBanner
            kind="rejected"
            at={abo.admin_rejected_at}
            reason={abo.admin_rejection_reason}
          />
        )}
        <Descriptions
          column={1}
          bordered
          size="small"
          style={{ marginBottom: 20 }}
        >
          <Descriptions.Item label={t("members.trial")}>
            {abo.is_trial ? (
              <Tag color="orange">{t("common.yes")}</Tag>
            ) : (
              <Tag color="green">{t("common.no")}</Tag>
            )}
          </Descriptions.Item>

          <Descriptions.Item label={t("members.member")}>
            {abo.member_first_name} {abo.member_last_name}
          </Descriptions.Item>
          <Descriptions.Item label={t("members.email")}>
            {abo.email}
          </Descriptions.Item>
          <Descriptions.Item label={t("sepa.mandate_status")}>
            {!hasActiveMandate ? (
              <Tag color="red" icon={<CloseCircleOutlined />}>
                {t("sepa.mandate_missing")}
              </Tag>
            ) : requiresSepaPaper && !paperReceived ? (
              // Digitally ready, but the tenant requires the signed paper and it
              // hasn't been recorded yet — amber, not a contradictory green.
              <Tag color="orange" icon={<ClockCircleOutlined />}>
                {t("sepa.mandate_paper_pending")}
              </Tag>
            ) : (
              <Tag color="green" icon={<CheckCircleOutlined />}>
                {t("sepa.mandate_active")}
              </Tag>
            )}
          </Descriptions.Item>
          {billingProfile?.sepa_mandate_reference && (
            <Descriptions.Item label={t("sepa.mandate_reference")}>
              {billingProfile.sepa_mandate_reference}
            </Descriptions.Item>
          )}
          {billingProfile?.sepa_mandate_signed_at && (
            <Descriptions.Item label={t("sepa.signed_at")}>
              {formatDate(billingProfile.sepa_mandate_signed_at)}
            </Descriptions.Item>
          )}
          {requiresSepaPaper && billingProfile && (
            <Descriptions.Item label={t("sepa.paper_label")}>
              <Checkbox
                checked={paperReceived}
                disabled={patchProfile.isPending}
                onChange={(e) => handlePaperToggle(e.target.checked)}
              >
                {t("sepa.paper_received")}
              </Checkbox>
            </Descriptions.Item>
          )}
          <Descriptions.Item label={t("members.share_type_variation")}>
            {variationLabel(abo.share_type_variation_string)}
          </Descriptions.Item>
          <Descriptions.Item label={t("members.valid_from")}>
            {formatDateWithFallback(abo.valid_from, "-")}
          </Descriptions.Item>
          <Descriptions.Item label={t("members.deliveries")}>
            {deliveries != null ? deliveries : "-"}x
          </Descriptions.Item>
          <Descriptions.Item label={t("members.price_per_delivery")}>
            {formatCurrency(Number(abo.price_per_delivery))}
          </Descriptions.Item>
          <Descriptions.Item label={t("members.valid_until")}>
            {formatDateWithFallback(abo.valid_until, "-")}
          </Descriptions.Item>
          <Descriptions.Item label={t("members.current_status")}>
            {aboStatus && (
              <Tag color={aboStatus.color} icon={aboStatus.icon}>
                {aboStatus.text}
              </Tag>
            )}
          </Descriptions.Item>
          {adminConfirmationAuditItems(abo, t, formatDateTime)}
        </Descriptions>
      </div>
    </Modal>
  );
};

