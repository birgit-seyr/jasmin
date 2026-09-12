import { useQueryClient } from "@tanstack/react-query";
import { Form, Input, Select } from "antd";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import {
  getSupportTicketsListQueryKey,
  useSupportTicketsCreate,
} from "@shared/api/generated/support/support";
import type {
  SupportTicketCreate,
  TicketPriorityEnum,
} from "@shared/api/generated/models";
import EditFormModal from "@shared/modals/shared/EditFormModal";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import { captureSupportContext } from "./captureSupportContext";

interface SupportTicketModalProps {
  open: boolean;
  onClose: () => void;
  /** Called with the new ticket id so the drawer can open its thread. */
  onCreated?: (id: string) => void;
}

interface TicketFormValues {
  subject: string;
  priority: TicketPriorityEnum;
  description: string;
}

/**
 * Report-a-problem modal. Mirrors ConsentDocumentModal (generated create hook +
 * ListQueryKey invalidation + notify/getErrorMessage) but built on the shared
 * EditFormModal primitive rather than a hand-rolled Modal.
 */
export default function SupportTicketModal({
  open,
  onClose,
  onCreated,
}: SupportTicketModalProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [form] = Form.useForm();

  // The Form.useForm store survives close/reopen (destroyOnHidden only clears
  // the DOM), so reset the fields on every open — otherwise the previously
  // typed subject/description linger.
  useEffect(() => {
    if (open) {
      form.resetFields();
      form.setFieldsValue({ priority: "normal" });
    }
  }, [open, form]);

  const createMutation = useSupportTicketsCreate({
    mutation: {
      onSuccess: (ticket) => {
        void queryClient.invalidateQueries({
          queryKey: getSupportTicketsListQueryKey(),
        });
        notify.success(t("support.modal.created"));
        onCreated?.(ticket.id ?? "");
        onClose();
      },
      onError: (err) => notify.error(getErrorMessage(err)),
    },
  });

  const priorityOptions = (["low", "normal", "high"] as const).map((p) => ({
    value: p,
    label: t(`support.priority.${p}`),
  }));

  return (
    <EditFormModal
      open={open}
      form={form}
      title={t("support.modal.title")}
      initialValues={null}
      okText={t("support.modal.submit")}
      loading={createMutation.isPending}
      onCancel={onClose}
      onSubmit={(values) => {
        const v = values as unknown as TicketFormValues;
        return createMutation.mutateAsync({
          data: {
            subject: v.subject,
            priority: v.priority,
            description: v.description,
            context: captureSupportContext(),
          } as SupportTicketCreate,
        });
      }}
    >
      <Form.Item
        name="subject"
        label={t("support.modal.subject_label")}
        rules={[{ required: true, max: 200 }]}
      >
        <Input placeholder={t("support.modal.subject_placeholder")} />
      </Form.Item>
      <Form.Item name="priority" label={t("support.modal.priority_label")}>
        <Select options={priorityOptions} />
      </Form.Item>
      <Form.Item
        name="description"
        label={t("support.modal.description_label")}
        rules={[{ required: true }]}
      >
        <Input.TextArea
          rows={6}
          placeholder={t("support.modal.description_placeholder")}
        />
      </Form.Item>
    </EditFormModal>
  );
}
