import type { FC } from "react";
import { useTranslation } from "react-i18next";

import { AdminRejectionModal } from "@shared/modals/AdminRejectionModal";
import type { MemberRecord } from "@features/members/pages/types";

interface RejectMemberModalProps {
  isOpen: boolean;
  onClose: () => void;
  member: MemberRecord | null;
  reason: string;
  onReasonChange: (value: string) => void;
  onReject: () => void;
  loading?: boolean;
}

/**
 * Reject a pending member application with an optional reason. Thin
 * wrapper over the shared {@link AdminRejectionModal} that supplies
 * the member-application copy.
 *
 * The reason is forwarded to the ``accounts.application_rejected`` email
 * so the applicant sees it verbatim — keep that in mind when writing it.
 * Triggered from the StatusButton in the Members table; the action is
 * irreversible from the UI.
 */
export const RejectMemberModal: FC<RejectMemberModalProps> = ({
  isOpen,
  onClose,
  member,
  reason,
  onReasonChange,
  onReject,
  loading = false,
}) => {
  const { t } = useTranslation();

  if (!member) return null;

  return (
    <AdminRejectionModal
      isOpen={isOpen}
      onClose={onClose}
      reason={reason}
      onReasonChange={onReasonChange}
      onReject={onReject}
      loading={loading}
      title={t("members.reject_modal_title")}
      heading={
        <>
          {member.first_name} {member.last_name}
          {member.member_number ? ` (#${member.member_number})` : ""}
        </>
      }
      warningTitle={t("members.reject_warning_title")}
      warningBody={t("members.reject_warning_body")}
      reasonPlaceholder={t("members.reject_reason_placeholder")}
    />
  );
};
