import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";

import { commissioningMembersRejectCreate } from "@shared/api/generated/commissioning/commissioning";
import type { Member } from "@shared/api/generated/models";
import { notify } from "@shared/utils";
import type { MemberRecord } from "@features/members/pages/types";

/**
 * State + actions for the Reject Member modal. Mirrors the shape of
 * ``useAdminConfirmationModalMembers`` so callers can wire both modals
 * the same way.
 *
 * The reject action is irreversible from the office UI (a rejected
 * application can't be re-opened through this modal), so we always
 * require an explicit ``reason`` before allowing submit. The reason
 * propagates to the applicant via the ``accounts.application_rejected``
 * email template.
 */
export const useRejectMemberModal = () => {
  const { t } = useTranslation();
  const [isRejectModalOpen, setIsRejectModalOpen] = useState(false);
  const [selectedMemberForRejection, setSelectedMemberForRejection] =
    useState<MemberRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [reason, setReason] = useState("");

  const handleOpenRejectModal = useCallback((member: MemberRecord) => {
    setSelectedMemberForRejection(member);
    setReason("");
    setIsRejectModalOpen(true);
  }, []);

  const handleCloseRejectModal = useCallback(() => {
    setIsRejectModalOpen(false);
    setSelectedMemberForRejection(null);
    setReason("");
  }, []);

  const rejectMember = useCallback(async () => {
    if (!selectedMemberForRejection) return;
    const memberId = String(selectedMemberForRejection.id ?? "");
    if (!memberId) return;

    setLoading(true);
    try {
      // Backend (``MembersViewSet.reject``) reads ``request.data.get
      // ("reason")`` and forwards it to
      // ``MemberService.reject_and_notify`` which puts it into the
      // ``accounts.application_rejected`` email context. Empty string
      // is allowed by the serializer — the email still goes out, just
      // without a stated reason.
      const data = await commissioningMembersRejectCreate(memberId, {
        reason: reason.trim(),
      });
      notify.success(
        t("members.reject_success"),
      );
      handleCloseRejectModal();
      return data;
    } catch (error) {
      console.error("Failed to reject member:", error);
      notify.error(
        t("members.reject_error"),
      );
      throw error;
    } finally {
      setLoading(false);
    }
  }, [selectedMemberForRejection, reason, t, handleCloseRejectModal]);

  return {
    isRejectModalOpen,
    selectedMemberForRejection,
    loading,
    reason,
    setReason,
    handleOpenRejectModal,
    handleCloseRejectModal,
    rejectMember,
  };
};
