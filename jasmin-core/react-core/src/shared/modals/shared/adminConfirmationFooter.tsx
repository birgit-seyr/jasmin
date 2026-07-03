import { CheckCircleOutlined, CloseCircleOutlined } from "@ant-design/icons";
import { Button } from "antd";
import type { ReactNode } from "react";
import ModalCloseFooter from "@shared/modals/ModalCloseFooter";

interface AdminConfirmationFooterArgs {
  /** Terminal row (already confirmed or rejected) → only a Close button. */
  isTerminal: boolean | undefined;
  onClose: () => void;
  onConfirm?: () => void;
  confirmLabel: string;
  cancelLabel: string;
  loading: boolean;
  /** Optional reject action (Members / Abos; CoopShares omits it). */
  onReject?: () => void;
  rejectLabel?: string;
}

/**
 * Footer for the admin-confirmation modals (Members / Abos / CoopShares).
 * Terminal rows get a single Close; otherwise Cancel + optional Reject +
 * Confirm. The per-modal shell content/width and the (already shared) status
 * banner / audit / tag stay in each modal — only this 3-state footer was
 * byte-duplicated.
 */
export function adminConfirmationFooter({
  isTerminal,
  onClose,
  onConfirm,
  confirmLabel,
  cancelLabel,
  loading,
  onReject,
  rejectLabel,
}: AdminConfirmationFooterArgs): ReactNode {
  if (isTerminal) {
    return [<ModalCloseFooter key="close" onClose={onClose} />];
  }
  return [
    <Button key="cancel" onClick={onClose} disabled={loading}>
      {cancelLabel}
    </Button>,
    ...(onReject && rejectLabel
      ? [
          <Button
            key="reject"
            danger
            onClick={onReject}
            disabled={loading}
            icon={<CloseCircleOutlined />}
          >
            {rejectLabel}
          </Button>,
        ]
      : []),
    <Button
      key="confirm"
      type="primary"
      loading={loading}
      onClick={onConfirm}
      icon={<CheckCircleOutlined />}
    >
      {confirmLabel}
    </Button>,
  ];
}
