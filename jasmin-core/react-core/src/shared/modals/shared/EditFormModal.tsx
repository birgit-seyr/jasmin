import type { FormInstance } from "antd";
import { Form, Modal } from "antd";
import { useCallback, useEffect, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useEnterToSubmit } from "./useEnterToSubmit";

export interface EditFormModalProps {
  open: boolean;
  title: ReactNode;
  /** Object with the values to populate the form when opening. */
  initialValues: Record<string, unknown> | null;
  onSubmit: (values: Record<string, unknown>) => void;
  onCancel: () => void;
  /** The Form.Item children. */
  children: ReactNode;
  /** Optional pre-existing form instance (e.g. when the parent watches values). */
  form?: FormInstance;
  /** Override the OK button label (defaults to common.save). */
  okText?: string;
  /** Override the Cancel button label. */
  cancelText?: string;
  /** Modal width. */
  width?: number | string;
  /** Loading state passed to the OK button. */
  loading?: boolean;
}

/**
 * Generic edit-form modal: renders an antd Modal containing a vertical Form,
 * pre-fills it from `initialValues` when opened, validates on OK, and submits
 * on Enter.
 */
export default function EditFormModal({
  open,
  title,
  initialValues,
  onSubmit,
  onCancel,
  children,
  form: externalForm,
  okText,
  cancelText,
  width,
  loading,
}: EditFormModalProps) {
  const { t } = useTranslation();
  const [internalForm] = Form.useForm();
  const form = externalForm ?? internalForm;

  useEffect(() => {
    if (open && initialValues) {
      form.setFieldsValue(initialValues);
    }
  }, [open, initialValues, form]);

  const handleOk = useCallback(async () => {
    try {
      const values = await form.validateFields();
      onSubmit(values as Record<string, unknown>);
    } catch (error) {
      console.error("Operation failed:", error);
      // validation failed, antd shows errors inline
    }
  }, [form, onSubmit]);

  const handleKeyDown = useEnterToSubmit(handleOk);

  return (
    <Modal
      title={title}
      open={open}
      onOk={handleOk}
      onCancel={onCancel}
      okText={okText ?? t("common.save")}
      cancelText={cancelText ?? t("common.cancel")}
      okButtonProps={{ loading }}
      width={width}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" onKeyDown={handleKeyDown}>
        {children}
      </Form>
    </Modal>
  );
}
