import { SendOutlined } from "@ant-design/icons";
import { Modal } from "antd";

import { ModalCancelSaveFooter } from "@shared/modals/shared";
import { CheckboxMultiSelectList } from "@shared/ui";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import { OfferSendingStatus } from "@shared/api/generated/models";

type Reseller = Pick<OfferSendingStatus, "id" | "sent" | "sent_at"> & {
  name: string;
};

interface SendOffersModalProps {
  open: boolean;
  onClose: () => void;
  resellers: Reseller[];
  onSend: (resellerIds: string[]) => Promise<void>;
  year: number;
  week: number;
  offerGroupName?: string;
}

export default function SendOffersModal({
  open,
  onClose,
  resellers,
  onSend,
  year,
  week,
  offerGroupName,
}: SendOffersModalProps) {
  const { t } = useTranslation();
  const [sending, setSending] = useState(false);

  // Initialize with all resellers selected (not already sent)
  const [selectedIds, setSelectedIds] = useState<string[]>(() =>
    resellers.filter((r) => !r.sent).map((r) => r.id)
  );

  // UI-1: reset to "all unsent selected" each time the modal OPENS — not on
  // every ``resellers`` array-identity change. The parent passes a new array
  // every render, so keying on ``resellers`` wiped the office's manual
  // de-selections mid-session (and setState-in-useMemo is a render-phase
  // anti-pattern). ``resellers`` is intentionally captured as of the open, so
  // it is omitted from the deps.
  useEffect(() => {
    if (open) {
      setSelectedIds(resellers.filter((r) => !r.sent).map((r) => r.id));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const notSentResellers = useMemo(
    () => resellers.filter((r) => !r.sent),
    [resellers]
  );

  const noneSelected = selectedIds.length === 0;

  const selectableItems = useMemo(
    () => notSentResellers.map((r) => ({ key: r.id, label: r.name })),
    [notSentResellers]
  );

  const handleSend = useCallback(async () => {
    if (selectedIds.length === 0) {
      notify.warning(t("commissioning.no_resellers_selected"));
      return;
    }

    setSending(true);
    try {
      await onSend(selectedIds);
      // Send is now ASYNC (enqueued as a Huey ``BackgroundJob``) so
      // this toast must NOT claim the work is done. The real status —
      // per-reseller success / failure / "already sent" — is shown by
      // the JobProgressDrawer that ``Offers.tsx`` opens on the parent
      // side once it has the ``job_id``.
      notify.info(
        t("commissioning.offers_send_queued"),
      );
      onClose();
    } catch (error) {
      notify.error(
        getErrorMessage(
          error,
          t("commissioning.failed_to_send_offers"),
        ),
      );
    } finally {
      setSending(false);
    }
  }, [selectedIds, onSend, onClose, t]);

  return (
    <Modal
      title={t("commissioning.send_offers_via_email")}
      open={open}
      onCancel={onClose}
      width={500}
      footer={
        <ModalCancelSaveFooter
          onCancel={onClose}
          onPrimary={handleSend}
          loading={sending}
          primaryDisabled={noneSelected}
          primaryIcon={<SendOutlined />}
          primaryLabel={`${t("commissioning.send")} (${selectedIds.length})`}
        />
      }
    >
      <div style={{ marginBottom: 16 }}>
        <p>
          {t(
            "commissioning.send_offers_description",
            { week, year }
          )}
          {offerGroupName && ` (${offerGroupName})`}
        </p>
      </div>

      {notSentResellers.length > 0 && (
        <CheckboxMultiSelectList
          items={selectableItems}
          selectedKeys={selectedIds}
          onChange={setSelectedIds}
          withSelectAll
        />
      )}

      {notSentResellers.length === 0 && (
        <div style={{ padding: 16, textAlign: "center", color: "var(--color-text-tertiary)" }}>
          {t("commissioning.all_offers_already_sent")}
        </div>
      )}

      {resellers.filter((r) => r.sent).length > 0 && (
        <div style={{ marginTop: 16, padding: 12, backgroundColor: "var(--color-bg-subtle)", borderRadius: 6 }}>
          <strong>
            {t("commissioning.already_sent")} (
            {resellers.filter((r) => r.sent).length}):
          </strong>
          <ul style={{ marginTop: 8, marginBottom: 0, paddingLeft: 20 }}>
            {resellers
              .filter((r) => r.sent)
              .map((r) => (
                <li key={r.id}>{r.name}</li>
              ))}
          </ul>
        </div>
      )}
    </Modal>
  );
}
