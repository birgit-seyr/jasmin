import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";

import { commissioningAbosRejectCreate } from "@shared/api/generated/commissioning/commissioning";
import { notify } from "@shared/utils";
import type { AboRecord } from "@features/abos/pages/types";

/**
 * Reject-modal state + actions for Subscriptions ("Abos"). Mirrors
 * ``useRejectMemberModal`` so the surface stays predictable. Posts via the
 * generated ``commissioningAbosRejectCreate`` (``SubscriptionViewSet.reject``).
 */
export const useRejectAboModal = () => {
  const { t } = useTranslation();
  const [isRejectModalOpen, setIsRejectModalOpen] = useState(false);
  const [selectedAboForRejection, setSelectedAboForRejection] =
    useState<AboRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [reason, setReason] = useState("");

  const handleOpenRejectModal = useCallback((abo: AboRecord) => {
    setSelectedAboForRejection(abo);
    setReason("");
    setIsRejectModalOpen(true);
  }, []);

  const handleCloseRejectModal = useCallback(() => {
    setIsRejectModalOpen(false);
    setSelectedAboForRejection(null);
    setReason("");
  }, []);

  const rejectAbo = useCallback(async () => {
    if (!selectedAboForRejection) return;
    const aboId = String(selectedAboForRejection.id ?? "");
    if (!aboId) return;

    setLoading(true);
    try {
      const data = await commissioningAbosRejectCreate(aboId, {
        reason: reason.trim(),
      });
      notify.success(t("members.reject_success"));
      handleCloseRejectModal();
      return data;
    } catch (error) {
      console.error("Failed to reject subscription:", error);
      notify.error(
        t("members.reject_error"),
      );
      throw error;
    } finally {
      setLoading(false);
    }
  }, [selectedAboForRejection, reason, t, handleCloseRejectModal]);

  return {
    isRejectModalOpen,
    selectedAboForRejection,
    loading,
    reason,
    setReason,
    handleOpenRejectModal,
    handleCloseRejectModal,
    rejectAbo,
  };
};
