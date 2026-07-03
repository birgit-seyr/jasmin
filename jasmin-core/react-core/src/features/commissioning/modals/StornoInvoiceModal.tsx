import { StopOutlined } from "@ant-design/icons";
import { Input, Modal, Space, Typography } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

const { Text } = Typography;

interface StornoInvoiceModalProps {
  open: boolean;
  /** Human-readable invoice number shown in the body. */
  invoiceLabel: string;
  /** Whether the storno create+upload is in flight. */
  loading: boolean;
  onCancel: () => void;
  /** Called with the (non-empty) correction reason when confirmed. */
  onConfirm: (reason: string) => void;
}

/**
 * Confirm dialog for cancelling (Storno) a finalized reseller invoice. Owns the
 * correction-reason input; the parent handles the actual mutation + PDF upload.
 */
export default function StornoInvoiceModal({
  open,
  invoiceLabel,
  loading,
  onCancel,
  onConfirm,
}: StornoInvoiceModalProps) {
  const { t } = useTranslation();
  const [reason, setReason] = useState("");

  // Reset the reason every time the dialog opens.
  useEffect(() => {
    if (open) setReason("");
  }, [open]);

  return (
    <Modal
      open={open}
      title={
        <Space>
          <StopOutlined className="text-error" />
          {t("commissioning.create_storno")}
        </Space>
      }
      onCancel={onCancel}
      onOk={() => onConfirm(reason)}
      confirmLoading={loading}
      okText={t("commissioning.create_storno")}
      okButtonProps={{ danger: true, disabled: !reason.trim() }}
    >
      <div style={{ marginBottom: 16 }}>
        <Text>
          {t("commissioning.storno_for_invoice")}:{" "}
          <Text strong>{invoiceLabel}</Text>
        </Text>
      </div>
      <div>
        <Text>{t("commissioning.correction_reason")} *</Text>
        <Input.TextArea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={3}
          placeholder={t("commissioning.storno_reason_placeholder")}
          style={{ marginTop: 8 }}
        />
      </div>
    </Modal>
  );
}
