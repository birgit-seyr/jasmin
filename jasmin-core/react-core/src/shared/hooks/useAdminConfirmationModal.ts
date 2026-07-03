import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";

export interface AdminStatus {
  variant: "adminConfirmed" | "adminPending" | "adminRejected";
  key: string;
  priority: number;
}

/** The status-bearing fields the priority/sorter logic reads. Both
 *  ``MemberRecord`` and ``AboRecord`` already carry these. */
export interface AdminConfirmableRecord extends TableRecord {
  admin_confirmed?: boolean;
  admin_rejected_at?: string | null;
  cancelled_at?: string | null;
}

interface UseAdminConfirmationModalOptions<TResp> {
  /** Backend confirm call — takes the record id. Its resolved payload type
   *  flows through to ``handleConfirm``'s ``onConfirmed`` callback. */
  confirmFn: (id: string) => Promise<TResp>;
  successKey: string;
  errorKey: string;
}

/**
 * Generic admin-confirmation modal hook — the single home for the Members and
 * Abos confirmation flows (their thin wrappers inject ``confirmFn`` + the i18n
 * keys and re-export under domain names like ``selectedMemberForConfirmation``).
 *
 * Owns: open / selected / loading state; the confirm mutation (surfacing the
 * backend's verbatim error message via ``getErrorMessage``, returning the
 * server payload so callers can patch e.g. the generated member number); the
 * priority ``getAdminStatus``; and the pinned, ascending-shaped
 * ``getAdminStatusSorter``.
 *
 * Consolidates two byte-identical copies that had already silently DRIFTED —
 * one ran the sorter the other documents as the 2026-06-08 bug, and only one
 * surfaced backend error messages.
 */
export function useAdminConfirmationModal<
  T extends AdminConfirmableRecord,
  TResp = unknown,
>({ confirmFn, successKey, errorKey }: UseAdminConfirmationModalOptions<TResp>) {
  const [isOpen, setIsOpen] = useState(false);
  const [selectedItem, setSelectedItem] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const { t } = useTranslation();

  const handleOpen = useCallback((item: T) => {
    setSelectedItem(item);
    setIsOpen(true);
  }, []);

  const handleClose = useCallback(() => {
    setIsOpen(false);
    setSelectedItem(null);
  }, []);

  const handleConfirm = useCallback(
    async (onConfirmed?: (data: TResp) => void) => {
      if (!selectedItem) return;

      setLoading(true);
      try {
        const data = await confirmFn(String(selectedItem.id ?? ""));
        notify.success(t(successKey));
        if (typeof onConfirmed === "function") {
          onConfirmed(data);
        }
        handleClose();
        return data;
      } catch (error) {
        // Surface the backend's verbatim message (e.g. a coop-share range
        // violation) rather than only the generic toast; falls back to the
        // key when the response has no recognisable error body.
        notify.error(getErrorMessage(error, t(errorKey)));
        throw error;
      } finally {
        setLoading(false);
      }
    },
    [selectedItem, confirmFn, successKey, errorKey, t, handleClose],
  );

  /** No-callback convenience that resolves to the server payload. */
  const confirm = useCallback(() => handleConfirm(), [handleConfirm]);

  const getAdminStatus = useCallback((record: T): AdminStatus => {
    // Priority drives the column sort: admin_pending (needs office action
    // TODAY) on top, then admin_confirmed (settled), admin_rejected
    // (terminal), cancelled (archival) at the bottom.
    if (record.admin_confirmed) {
      return { variant: "adminConfirmed", key: "admin_confirmed", priority: 3 };
    } else if (record.admin_rejected_at) {
      return { variant: "adminRejected", key: "admin_rejected", priority: 2 };
    } else if (record.cancelled_at) {
      return { variant: "adminPending", key: "cancelled", priority: 1 };
    }
    return { variant: "adminPending", key: "admin_pending", priority: 4 };
  }, []);

  const getAdminStatusSorter = useCallback(
    (a: TableRecord, b: TableRecord, sortOrder?: "ascend" | "descend") => {
      // Pin the placeholder "add new row" (``key === -1``) to the very top
      // regardless of direction — AntD reverses the result for descend, so we
      // flip the sign ourselves.
      if (a.key === -1) return sortOrder === "descend" ? 1 : -1;
      if (b.key === -1) return sortOrder === "descend" ? -1 : 1;
      const statusA = getAdminStatus(a as T);
      const statusB = getAdminStatus(b as T);
      // ASCENDING-shaped (A − B): AntD inverts for descend, so a descend-sorted
      // column puts HIGH priority (admin_pending) at the top — the semantic
      // getAdminStatus documents. Returning B − A is the 2026-06-08 bug that
      // pushed pending rows to the bottom.
      return statusA.priority - statusB.priority;
    },
    [getAdminStatus],
  );

  return {
    isOpen,
    selectedItem,
    loading,
    handleOpen,
    handleClose,
    handleConfirm,
    confirm,
    getAdminStatus,
    getAdminStatusSorter,
  };
}
