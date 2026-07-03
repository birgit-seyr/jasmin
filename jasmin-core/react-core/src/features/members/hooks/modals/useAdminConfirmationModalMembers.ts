import { commissioningMembersConfirmCreate } from "@shared/api/generated/commissioning/commissioning";
import type { Member } from "@shared/api/generated/models";
import { useAdminConfirmationModal } from "@hooks/useAdminConfirmationModal";
import type { MemberRecord } from "@features/members/pages/types";

/**
 * Members admin-confirmation modal — a thin domain wrapper over the shared
 * ``useAdminConfirmationModal`` hook. Injects the Members confirm call (no
 * request body) + i18n keys and re-exports the generic surface under the
 * Member-specific names the page/tests already consume.
 */
export const useAdminConfirmationModalMembers = () => {
  const modal = useAdminConfirmationModal<MemberRecord, Member>({
    confirmFn: (id) => commissioningMembersConfirmCreate(id),
    successKey: "members.admin_confirmation_success",
    errorKey: "members.admin_confirmation_error",
  });

  return {
    isAdminConfirmationModalOpen: modal.isOpen,
    selectedMemberForConfirmation: modal.selectedItem,
    loading: modal.loading,
    handleOpenAdminConfirmationModal: modal.handleOpen,
    handleCloseAdminConfirmationModal: modal.handleClose,
    handleConfirmMember: modal.handleConfirm,
    // Simple version without callback requirement; resolves to the fresh
    // Member payload (incl. the generated member_number) so the caller can
    // patch the table row with every field the backend touched.
    confirmMember: modal.confirm,
    getAdminStatus: modal.getAdminStatus,
    getAdminStatusSorter: modal.getAdminStatusSorter,
  };
};
