import type { FC } from "react";
import { Modal, Checkbox, Typography, Descriptions, Tag } from "antd";
import { usePaperReceivedToggle } from "@hooks/usePaperReceivedToggle";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import {
  getCommissioningMembersListQueryKey,
  useCommissioningMembersPartialUpdate,
} from "@shared/api/generated/commissioning/commissioning";
import type { Member } from "@shared/api/generated/models";
import {
  adminConfirmationAuditItems,
  getAdminConfirmationStatus,
  ModalStatusBanner,
  adminConfirmationFooter,
} from "@shared/modals/shared";
import { useDateFormat, useTenant, useTimeFormat } from "@hooks/index";
import type { MemberRecord } from "@features/members/pages/types";

const { Title } = Typography;

interface AdminConfirmationModalMembersProps {
  isOpen: boolean;
  onClose: () => void;
  member: MemberRecord | null;
  onConfirm?: () => void;
  /**
   * Optional handler that closes this modal and opens the
   * RejectMemberModal for the same member. When provided, a
   * destructive "Reject" button appears next to "Confirm" in the
   * footer for pending members. When omitted, no reject control
   * shows — keeps the modal backward-compatible for callers that
   * haven't wired the reject flow yet.
   */
  onReject?: () => void;
  loading?: boolean;
}

export const AdminConfirmationModalMembers: FC<
  AdminConfirmationModalMembersProps
> = ({ isOpen, onClose, member, onConfirm, onReject, loading = false }) => {
  const { t } = useTranslation();
  const { formatDateTime } = useTimeFormat();
  const { formatDateWithFallback } = useDateFormat();
  const queryClient = useQueryClient();
  const { getSetting } = useTenant();
  const requiresMembershipPaper = Boolean(
    getSetting("requires_paper_signature_for_membership", false),
  );

  // Office-only: tick once the signed paper membership declaration arrives
  // (stamps Member.membership_paper_received_at).
  const patchMember = useCommissioningMembersPartialUpdate();
  const { paperReceived, handlePaperToggle } = usePaperReceivedToggle({
    initialValue: Boolean(member?.membership_paper_received_at),
    id: member?.id ? String(member.id) : undefined,
    patch: (id, value) =>
      patchMember.mutateAsync({
        id,
        data: { membership_paper_received_at: value } as Member,
      }),
    onPatched: () =>
      void queryClient.invalidateQueries({
        queryKey: getCommissioningMembersListQueryKey(),
      }),
  });

  if (!member) {
    return null;
  }

  const memberStatus = getAdminConfirmationStatus(member, t);
  const isRejected = !!member.admin_rejected_at;

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
        isTerminal: member.admin_confirmed || isRejected,
        onClose,
        onConfirm,
        confirmLabel: t("members.confirm_member"),
        cancelLabel: t("common.cancel"),
        loading,
        onReject,
        rejectLabel: t("members.reject_member"),
      })}
      width={600}
      destroyOnHidden
    >
      <div style={{ padding: "20px 0" }}>
        <Title level={4} style={{ marginBottom: 24 }}>
          # {member.member_number} - {member.first_name} {member.last_name}
        </Title>

        {isRejected && (
          <ModalStatusBanner
            kind="rejected"
            at={member.admin_rejected_at}
            reason={member.admin_rejection_reason}
          />
        )}

        <Descriptions
          column={1}
          bordered
          size="small"
          style={{ marginBottom: 20 }}
        >
          {member.is_trial && (
            <Descriptions.Item label={t("members.member_type")}>
              <Tag color="blue">{t("members.trial_member")}</Tag>
            </Descriptions.Item>
          )}
          <Descriptions.Item label={t("members.member_number_long")}>
            {member.member_number}
          </Descriptions.Item>
          <Descriptions.Item label={t("members.entry_date_long")}>
            {formatDateWithFallback(member.entry_date, "-")}
          </Descriptions.Item>

          {member.company_name && (
            <Descriptions.Item label={t("members.company_name")}>
              {member.company_name}
            </Descriptions.Item>
          )}

          {member.first_name && (
            <Descriptions.Item label={t("members.first_name")}>
              {member.first_name}
            </Descriptions.Item>
          )}

          {member.last_name && (
            <Descriptions.Item label={t("members.last_name")}>
              {member.last_name}
            </Descriptions.Item>
          )}
          {member.email && (
            <Descriptions.Item label={t("members.email")}>
              {member.email}
            </Descriptions.Item>
          )}

          <Descriptions.Item label={t("members.current_status")}>
            {memberStatus && (
              <Tag color={memberStatus.color} icon={memberStatus.icon}>
                {memberStatus.text}
              </Tag>
            )}
          </Descriptions.Item>
          {requiresMembershipPaper && (
            <Descriptions.Item label={t("members.membership_paper_label")}>
              <Checkbox
                checked={paperReceived}
                disabled={patchMember.isPending}
                onChange={(e) => handlePaperToggle(e.target.checked)}
              >
                {t("members.membership_paper_received")}
              </Checkbox>
            </Descriptions.Item>
          )}
          {adminConfirmationAuditItems(member, t, formatDateTime)}
        </Descriptions>
      </div>
    </Modal>
  );
};

