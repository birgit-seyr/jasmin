import { Button, Modal, Result } from "antd";
import { useTranslation } from "react-i18next";

interface SuccessModalProps {
  open: boolean;
  onClose: () => void;
  /** Defaults to a generic "Thank you!". */
  title?: string;
  subtitle?: string;
}

/**
 * A small "thank you" success modal — AntD ``Result`` (success) inside a
 * ``Modal``. Reusable for any post-action confirmation (e.g. after creating a
 * subscription).
 */
export default function SuccessModal({
  open,
  onClose,
  title,
  subtitle,
}: SuccessModalProps) {
  const { t } = useTranslation();
  return (
    <Modal open={open} onCancel={onClose} footer={null} centered>
      <Result
        status="success"
        title={title ?? t("common.thank_you")}
        subTitle={subtitle}
        extra={
          <Button type="primary" onClick={onClose}>
            {t("common.close")}
          </Button>
        }
      />
    </Modal>
  );
}
