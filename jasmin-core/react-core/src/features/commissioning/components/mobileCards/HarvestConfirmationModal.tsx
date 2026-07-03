import { InputNumber, Modal } from "antd";
import { useTranslation } from "react-i18next";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";

interface HarvestConfirmationModalProps {
  record: TableRecord | null;
  amount: number | null;
  saving: boolean;
  onChangeAmount: (value: number | null) => void;
  onCancel: () => void;
  onConfirm: () => void;
}

export function HarvestConfirmationModal({
  record,
  amount,
  saving,
  onChangeAmount,
  onCancel,
  onConfirm,
}: HarvestConfirmationModalProps) {
  const { t } = useTranslation();

  return (
    <Modal
      open={!!record}
      onCancel={onCancel}
      onOk={onConfirm}
      confirmLoading={saving}
      title={t("commissioning.actual_harvest")}
      okText={t("commissioning.set_as_expected_harvest")}
      width={320}
      centered
    >
      {record && (
        <div style={{ textAlign: "center", padding: "8px 0" }}>
          <div style={{ fontWeight: 600, marginBottom: 12 }}>
            {(record.computed_article_with_size as string) ||
              (record.share_article_name as string)}
          </div>
          <div style={{ color: "var(--color-text-muted)", fontSize: "0.85em", marginBottom: 12 }}>
            {t("commissioning.expected_harvest")}:{" "}
            {(record.computed_total_amount as number) || 0}{" "}
            {record.computed_unit_label as string}
          </div>
          <InputNumber
            value={amount}
            onChange={onChangeAmount}
            min={0}
            size="large"
            style={{ width: "100%", fontSize: 18 }}
            addonAfter={record.computed_unit_label as string}
          />
        </div>
      )}
    </Modal>
  );
}
