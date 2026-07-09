import { commissioningAbosRejectCreate } from "@shared/api/generated/commissioning/commissioning";
import { useRejectModal } from "@hooks/useRejectModal";
import type { AboRecord } from "@features/abos/pages/types";

/**
 * Abos reject modal — a thin domain wrapper over the shared ``useRejectModal``
 * hook. Injects the Abos reject call (``SubscriptionViewSet.reject``) + i18n
 * keys and re-exports the generic surface under the Abo-specific names the page
 * already consumes.
 */
export const useRejectAboModal = () => {
  const modal = useRejectModal<AboRecord>({
    rejectFn: (id, reason) => commissioningAbosRejectCreate(id, { reason }),
    successKey: "members.reject_success",
    errorKey: "members.reject_error",
  });

  return {
    isRejectModalOpen: modal.isOpen,
    selectedAboForRejection: modal.selectedItem,
    loading: modal.loading,
    reason: modal.reason,
    setReason: modal.setReason,
    handleOpenRejectModal: modal.handleOpen,
    handleCloseRejectModal: modal.handleClose,
    rejectAbo: modal.reject,
  };
};
