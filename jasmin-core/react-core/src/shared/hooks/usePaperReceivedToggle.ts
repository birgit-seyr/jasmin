import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { notify } from "@shared/utils";

interface UsePaperReceivedToggleOptions {
  /** Current stored value (true once the ``*_paper_received_at`` field is set). */
  initialValue: boolean;
  /** Record id, or undefined while it loads (the toggle is a no-op then). */
  id: string | undefined;
  /** Persist the new value — the caller builds its own typed Orval mutation.
   *  ``value`` is the ISO date (paper received) or null (un-received). */
  patch: (id: string, value: string | null) => Promise<unknown>;
  /** Run after a successful patch — typically a query invalidation. */
  onPatched: () => void;
}

/**
 * Optimistic "paper signature received" Switch handler, shared by the Members
 * (membership declaration) and Abos (SEPA mandate) admin-confirmation modals.
 * Owns the local state + optimistic-set / revert-on-error + the error toast; the
 * feature passes in its own mutation, field, and invalidation, so this hook
 * stays in ``src/shared`` and imports no feature.
 */
export function usePaperReceivedToggle({
  initialValue,
  id,
  patch,
  onPatched,
}: UsePaperReceivedToggleOptions) {
  const { t } = useTranslation();
  const [paperReceived, setPaperReceived] = useState(false);

  useEffect(() => {
    setPaperReceived(initialValue);
  }, [initialValue]);

  const handlePaperToggle = async (checked: boolean) => {
    if (!id) return;
    setPaperReceived(checked); // optimistic
    try {
      await patch(id, checked ? new Date().toISOString().slice(0, 10) : null);
      onPatched();
    } catch {
      setPaperReceived(!checked); // revert on failure
      notify.error(t("common.error"));
    }
  };

  return { paperReceived, handlePaperToggle };
}
