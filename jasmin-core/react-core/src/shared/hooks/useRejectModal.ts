import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import { notify } from "@shared/utils";

interface UseRejectModalOptions<TResp> {
  /** Backend reject call — takes the record id + the trimmed reason string. Its
   *  resolved payload flows through to ``reject``'s return so callers can patch
   *  the affected row with whatever fields the backend touched. */
  rejectFn: (id: string, reason: string) => Promise<TResp>;
  successKey: string;
  errorKey: string;
}

/**
 * Generic reject-modal hook — the single home for the Members and Abos reject
 * flows (their thin wrappers inject ``rejectFn`` + the i18n keys and re-export
 * the generic surface under domain names like ``selectedMemberForRejection`` /
 * ``rejectMember``).
 *
 * Owns: open / selected / loading / reason state; the reject mutation (trims the
 * reason, notifies success/error, closes on success, returns the server payload).
 * The reject action is irreversible from the office UI, so callers gate submit on
 * an explicit reason; the reason propagates to the applicant via the rejection
 * email template.
 */
export function useRejectModal<T extends TableRecord, TResp = unknown>({
  rejectFn,
  successKey,
  errorKey,
}: UseRejectModalOptions<TResp>) {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const [selectedItem, setSelectedItem] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [reason, setReason] = useState("");

  const handleOpen = useCallback((item: T) => {
    setSelectedItem(item);
    setReason("");
    setIsOpen(true);
  }, []);

  const handleClose = useCallback(() => {
    setIsOpen(false);
    setSelectedItem(null);
    setReason("");
  }, []);

  const reject = useCallback(async () => {
    if (!selectedItem) return;
    const id = String(selectedItem.id ?? "");
    if (!id) return;

    setLoading(true);
    try {
      const data = await rejectFn(id, reason.trim());
      notify.success(t(successKey));
      handleClose();
      return data;
    } catch (error) {
      console.error("Failed to reject:", error);
      notify.error(t(errorKey));
      throw error;
    } finally {
      setLoading(false);
    }
  }, [selectedItem, reason, rejectFn, successKey, errorKey, t, handleClose]);

  return {
    isOpen,
    selectedItem,
    loading,
    reason,
    setReason,
    handleOpen,
    handleClose,
    reject,
  };
}
