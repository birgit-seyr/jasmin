import { Button } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

interface ModalCancelSaveFooterProps {
  /** Fired by the left (cancel) button. */
  onCancel: () => void;
  /** Fired by the right (primary) button. */
  onPrimary: () => void;
  /** Loading state — disables Cancel + shows spinner on the primary. */
  loading?: boolean;
  /**
   * Disables the primary button. Cancel stays clickable unless
   * ``loading`` is also true (so the office can always bail out).
   */
  primaryDisabled?: boolean;
  /** Overrides the default ``common.save`` label on the primary. */
  primaryLabel?: ReactNode;
  /** Optional leading icon on the primary button. */
  primaryIcon?: ReactNode;
  /**
   * When true, the primary becomes a destructive (red) button —
   * use for "Reject", "Delete" etc.
   */
  primaryDanger?: boolean;
  /** Overrides the default ``common.cancel`` label on the left. */
  cancelLabel?: ReactNode;
}

/**
 * The canonical "Cancel + primary action" footer used by ~5 modals in
 * the codebase (RejectMember, RejectAbo, ResellerInvoiceSettings,
 * SendOffers, VirtualComponent). Encapsulates the conventions:
 *
 *   * Left button = secondary (default styling), labelled
 *     ``common.cancel`` by default. Disabled while ``loading``.
 *   * Right button = ``type="primary"``, labelled ``common.save`` by
 *     default. Carries an optional icon and danger styling.
 *
 * Modals with more elaborate footers (EmailTemplateEditor's
 * reset+cancel+save, AdminConfirmationModal*'s conditional 3-button
 * shape, LoggingModal's close-only) stay inline — forcing them
 * through this API would just trade duplication for prop-explosion.
 *
 * Usage::
 *
 *   <Modal
 *     ...
 *     footer={
 *       <ModalCancelSaveFooter
 *         onCancel={onClose}
 *         onPrimary={handleSave}
 *         loading={saving}
 *         primaryIcon={<SaveOutlined />}
 *       />
 *     }
 *   >
 */
export const ModalCancelSaveFooter = ({
  onCancel,
  onPrimary,
  loading = false,
  primaryDisabled = false,
  primaryLabel,
  primaryIcon,
  primaryDanger = false,
  cancelLabel,
}: ModalCancelSaveFooterProps) => {
  const { t } = useTranslation();
  return (
    <>
      <Button key="cancel" onClick={onCancel} disabled={loading}>
        {cancelLabel ?? t("common.cancel")}
      </Button>
      <Button
        key="primary"
        type="primary"
        danger={primaryDanger}
        icon={primaryIcon}
        loading={loading}
        disabled={primaryDisabled}
        onClick={onPrimary}
      >
        {primaryLabel ?? t("common.save")}
      </Button>
    </>
  );
};

export default ModalCancelSaveFooter;
