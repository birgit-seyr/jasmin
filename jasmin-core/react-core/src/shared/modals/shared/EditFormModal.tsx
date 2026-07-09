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
  /**
   * Called with the validated form values. May be async — the modal awaits it
   * and shows the ``loading`` spinner while it resolves (drive ``loading`` from
   * ``useModalMutation``'s ``saving`` flag). The handler owns its own error
   * toast; validation failures never reach here. Any resolved value is ignored.
   */
  onSubmit: (values: Record<string, unknown>) => void | Promise<unknown>;
  onCancel: () => void;
  /** The Form.Item children. */
  children: ReactNode;
  /** Optional non-form content rendered above the Form (e.g. an intro line). */
  description?: ReactNode;
  /** Optional pre-existing form instance (e.g. when the parent watches values). */
  form?: FormInstance;
  /** Override the OK button label (defaults to common.save). */
  okText?: string;
  /** Override the Cancel button label. */
  cancelText?: string;
  /** Modal width. */
  width?: number | string;
  /** Loading state — spins the OK button and disables Cancel. */
  loading?: boolean;
  /** Passed through to the antd Form (defaults to antd's own default). */
  requiredMark?: boolean;
}

/**
 * Generic edit-form modal: renders an antd Modal containing a vertical Form,
 * pre-fills it from `initialValues` when opened, validates on OK, submits on
 * Enter, and delegates the mutation to `onSubmit`.
 *
 * Pass a memoized `initialValues` object — the populate effect keys off its
 * identity, so a fresh object every render would clobber in-progress edits.
 */
export default function EditFormModal({
  open,
  title,
  initialValues,
  onSubmit,
  onCancel,
  children,
  description,
  form: externalForm,
  okText,
  cancelText,
  width,
  loading,
  requiredMark,
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
    let values: Record<string, unknown>;
    try {
      values = (await form.validateFields()) as Record<string, unknown>;
    } catch {
      // validation failed — antd shows the errors inline, no toast.
      return;
    }
    try {
      await onSubmit(values);
    } catch (error) {
      console.error("Submit failed:", error);
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
      cancelButtonProps={{ disabled: loading }}
      width={width}
      destroyOnHidden
    >
      {description}
      <Form
        form={form}
        layout="vertical"
        requiredMark={requiredMark}
        onKeyDown={handleKeyDown}
      >
        {children}
      </Form>
    </Modal>
  );
}
