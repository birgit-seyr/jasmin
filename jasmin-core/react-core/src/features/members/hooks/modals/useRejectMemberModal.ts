import { commissioningMembersRejectCreate } from "@shared/api/generated/commissioning/commissioning";
import type { Member } from "@shared/api/generated/models";
import { useRejectModal } from "@hooks/useRejectModal";
import type { MemberRecord } from "@features/members/pages/types";

/**
 * Members reject modal — a thin domain wrapper over the shared
 * ``useRejectModal`` hook. Injects the Members reject call + i18n keys and
 * re-exports the generic surface under the Member-specific names the page/tests
 * already consume.
 *
 * Backend (``MembersViewSet.reject``) forwards the ``reason`` to
 * ``MemberService.reject_and_notify`` which puts it into the
 * ``accounts.application_rejected`` email context. Empty string is allowed by
 * the serializer — the email still goes out, just without a stated reason. The
 * resolved payload (incl. any stamped fields) flows back so the caller can patch
 * the table row.
 */
export const useRejectMemberModal = () => {
  const modal = useRejectModal<MemberRecord, Member>({
    rejectFn: (id, reason) =>
      commissioningMembersRejectCreate(id, { reason }),
    successKey: "members.reject_success",
    errorKey: "members.reject_error",
  });

  return {
    isRejectModalOpen: modal.isOpen,
    selectedMemberForRejection: modal.selectedItem,
    loading: modal.loading,
    reason: modal.reason,
    setReason: modal.setReason,
    handleOpenRejectModal: modal.handleOpen,
    handleCloseRejectModal: modal.handleClose,
    rejectMember: modal.reject,
  };
};
