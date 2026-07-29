import { Form, Input, InputNumber, Modal } from "antd";
import type { FC } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { cultivationBedTypesCreate } from "@shared/api/generated/cultivation/cultivation";
import type { BedType } from "@shared/api/generated/models";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";

interface BedTypeModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: (created: BedType) => void;
  /** Pin above a parent modal when opened from within one. */
  zIndex?: number;
}

/**
 * Small quick-create modal for a bed type — opened from the PlotContent modal so
 * a missing bed type can be added inline (mirrors the "add share article" flow).
 */
const BedTypeModal: FC<BedTypeModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
  zIndex,
}) => {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  const close = () => {
    form.resetFields();
    onClose();
  };

  const handleOk = async () => {
    let values: { name: string; length_in_m: number; width_in_m: number };
    try {
      values = await form.validateFields();
    } catch {
      return; // inline validation errors
    }
    setSaving(true);
    try {
      const created = await cultivationBedTypesCreate({
        name: values.name,
        length_in_m: values.length_in_m,
        width_in_m: String(values.width_in_m),
      } as unknown as BedType);
      notify.success(t("common.saved_successfully"));
      form.resetFields();
      onSuccess?.(created as unknown as BedType);
      onClose();
    } catch (error) {
      notify.error(getErrorMessage(error, t("common.error_saving")));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={t("cultivation.new_bed_type")}
      open={isOpen}
      onOk={handleOk}
      onCancel={close}
      confirmLoading={saving}
      okText={t("common.save")}
      cancelText={t("common.cancel")}
      zIndex={zIndex}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" requiredMark>
        <Form.Item
          name="name"
          label={t("cultivation.bed_type_name")}
          rules={[{ required: true }]}
        >
          <Input />
        </Form.Item>
        <Form.Item
          name="length_in_m"
          label={t("cultivation.length_in_m")}
          rules={[{ required: true }]}
        >
          <InputNumber min={1} step={1} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item
          name="width_in_m"
          label={t("cultivation.width_in_m")}
          rules={[{ required: true }]}
        >
          <InputNumber min={0} step={0.01} style={{ width: "100%" }} />
        </Form.Item>
      </Form>
    </Modal>
  );
};

export default BedTypeModal;
