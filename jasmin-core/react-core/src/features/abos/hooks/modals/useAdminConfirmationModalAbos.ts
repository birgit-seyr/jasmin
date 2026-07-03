import { commissioningAbosConfirmCreate } from "@shared/api/generated/commissioning/commissioning";
import { useAdminConfirmationModal } from "@hooks/useAdminConfirmationModal";
import type { AboRecord } from "@features/abos/pages/types";

/**
 * Abos admin-confirmation modal — a thin domain wrapper over the shared
 * ``useAdminConfirmationModal`` hook. Injects the Abos confirm call + i18n
 * keys and re-exports the generic surface under the Abo-specific names the
 * page/columns already consume. The confirm endpoint takes no body
 * (``request=None`` in the backend schema).
 */
export const useAdminConfirmationModalAbos = () => {
  const modal = useAdminConfirmationModal<AboRecord>({
    confirmFn: (id) => commissioningAbosConfirmCreate(id),
    successKey: "members.admin_confirmation_success",
    errorKey: "members.admin_confirmation_error",
  });

  return {
    isAdminConfirmationModalOpen: modal.isOpen,
    selectedAboForConfirmation: modal.selectedItem,
    loading: modal.loading,
    handleOpenAdminConfirmationModal: modal.handleOpen,
    handleCloseAdminConfirmationModal: modal.handleClose,
    handleConfirmAbo: modal.handleConfirm,
    confirmAbo: modal.confirm,
    getAdminStatus: modal.getAdminStatus,
    getAdminStatusSorter: modal.getAdminStatusSorter,
  };
};
