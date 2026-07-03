import { Button } from "antd";
import { useTranslation } from "react-i18next";

/**
 * Footer for close-only modals (no save / primary action) — a single "Close"
 * button. For modals WITH a primary action use ``ModalCancelSaveFooter``; its
 * docstring deliberately keeps close-only footers out (would trade duplication
 * for prop-explosion), so this is the dedicated tiny component for them.
 *
 * Usage: ``<Modal footer={<ModalCloseFooter onClose={onClose} />} ...>``.
 */
export default function ModalCloseFooter({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  return (
    <Button key="close" onClick={onClose}>
      {t("common.close")}
    </Button>
  );
}
