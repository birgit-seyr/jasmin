import { Modal } from "antd";
import { useTranslation } from "react-i18next";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import NumberInput from "@shared/ui/NumberInput";
import "./HarvestConfirmationModal.css";

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
        <div className="harvest-confirmation">
          <div className="harvest-confirmation-article">
            {(record.computed_article_with_size as string) ||
              (record.share_article_name as string)}
          </div>
          <div className="harvest-confirmation-expected">
            {t("commissioning.expected_harvest")}:{" "}
            {(record.computed_total_amount as number) || 0}{" "}
            {record.computed_unit_label as string}
          </div>
          <NumberInput
            aria-label={t("commissioning.actual_harvest")}
            value={amount}
            onChange={onChangeAmount}
            min={0}
            precision={2}
            size="large"
            className="harvest-confirmation-amount"
            addonAfter={record.computed_unit_label as string}
          />
        </div>
      )}
    </Modal>
  );
}
