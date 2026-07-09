import { useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  DatePicker,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Typography,
} from "antd";
import dayjs, { Dayjs } from "dayjs";
import DOMPurify from "dompurify";
import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import ReactQuill from "react-quill-new";
import "react-quill-new/dist/quill.snow.css";
import {
  getCommissioningConsentDocumentsListQueryKey,
  useCommissioningConsentDocumentsCreate,
} from "@shared/api/generated/commissioning/commissioning";
import type { ConsentDocument } from "@shared/api/generated/models";
import { notify, toApiDate } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";

const { Text } = Typography;

// Full rich-text toolbar (same set as the email-template editor) — consent
// documents are authored as HTML and rendered (sanitised) to members.
const QUILL_MODULES = {
  toolbar: [
    [{ header: [1, 2, 3, false] }],
    ["bold", "italic", "underline", "strike"],
    [{ list: "ordered" }, { list: "bullet" }],
    [{ color: [] }, { background: [] }],
    ["link"],
    ["clean"],
  ],
};

export type ConsentDocumentModalMode = "create" | "view";

interface ConsentDocumentModalProps {
  open: boolean;
  mode: ConsentDocumentModalMode;
  /** Required in ``view`` mode — the row being inspected. Ignored in ``create``. */
  document?: ConsentDocument | null;
  /** Tenant defaults — passed in rather than re-resolved here so the
   *  modal stays decoupled from the page's data hooks. */
  tenantLanguage: string;
  dateFormat: string;
  onClose: () => void;
}

interface NewVersionFormValues {
  kind: string;
  version: string;
  title?: string;
  valid_from: Dayjs;
  body: string;
}

/**
 * Single modal that covers both "publish a new ConsentDocument version"
 * (mode=create) and "show me the body of an existing version"
 * (mode=view). Body content is plain text — see
 * ConfigurationConsents notes for the rationale (audit-friendly
 * SHA-256, no XSS surface). If you ever switch to markdown, render
 * the view side with ``react-markdown`` and keep the editor as
 * ``TextArea`` so the on-disk format stays the same.
 */
export default function ConsentDocumentModal({
  open,
  mode,
  document,
  tenantLanguage,
  dateFormat,
  onClose,
}: ConsentDocumentModalProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<NewVersionFormValues>();

  // Translated options — keyed off ``t`` so a language switch at
  // runtime re-renders the dropdown with the new labels. Module-level
  // constants don't have access to ``t``, hence ``useMemo``.
  const kindOptions = useMemo(
    () =>
      (["privacy", "sepa", "withdrawal", "terms", "coop_contract"] as const).map(
        (k) => ({
          value: k,
          label: t(`consent.kind.${k}`, k),
        }),
      ),
    [t],
  );

  // Side-effects live on the mutation config, not in the handler —
  // matches EmailTemplateEditorModal / VirtualComponentModal etc.
  // ``notify`` is the project's toast wrapper (not antd's ``message``)
  // so toasts pick up the global styling + accessibility shims.
  const createMutation = useCommissioningConsentDocumentsCreate({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({
          queryKey: getCommissioningConsentDocumentsListQueryKey(),
        });
        notify.success(t("consent.admin.created"));
        onClose();
      },
      onError: (err) => notify.error(getErrorMessage(err)),
    },
  });

  // Reset the form whenever the modal opens in create mode — guards
  // against stale values from a previous open-then-cancel cycle.
  useEffect(() => {
    if (open && mode === "create") {
      form.resetFields();
      form.setFieldsValue({ valid_from: dayjs() });
    }
  }, [open, mode, form]);

  const handleCreate = async () => {
    let values: NewVersionFormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    createMutation.mutate({
      data: {
        kind: values.kind as never,
        version: values.version,
        locale: tenantLanguage,
        title: values.title || "",
        valid_from: toApiDate(values.valid_from)!,
        body: values.body,
      } as ConsentDocument,
    });
  };

  if (mode === "view") {
    return (
      <Modal
        open={open}
        // Header the human title, not the kind (fall back to the kind label
        // only when a document genuinely has no title).
        title={
          document
            ? document.title ||
              t(`consent.kind.${document.kind}`, document.kind)
            : ""
        }
        onCancel={onClose}
        footer={null}
        width={720}
      >
        {document && (
          <Space direction="vertical" className="w-full" size={4}>
            <Text strong>
              {t("consent.admin.col_version")} {document.version}
            </Text>
            <Text type="secondary">
              {t("consent.admin.col_effective_from")}:{" "}
              {document.valid_from
                ? dayjs(document.valid_from).format(dateFormat)
                : "—"}
            </Text>
            <Text type="secondary" style={{ fontSize: 11 }}>
              SHA-256:{" "}
              <Text code style={{ fontSize: 11 }}>
                {document.body_sha256}
              </Text>
            </Text>
            <div
              style={{
                marginTop: 8,
                maxHeight: 480,
                overflowY: "auto",
                padding: 12,
                border: "1px solid var(--ant-color-border, #d9d9d9)",
                borderRadius: 4,
                background: "var(--ant-color-bg-container, #fafafa)",
                fontSize: 13,
              }}
              // Body is office-authored HTML (Quill); sanitise on render.
              dangerouslySetInnerHTML={{
                __html: DOMPurify.sanitize(document.body),
              }}
            />
          </Space>
        )}
      </Modal>
    );
  }

  return (
    <Modal
      open={open}
      title={t("consent.admin.new_version")}
      onCancel={onClose}
      onOk={handleCreate}
      okText={t("consent.admin.publish")}
      okButtonProps={{ loading: createMutation.isPending }}
      width={720}
    >
      <Form<NewVersionFormValues>
        form={form}
        layout="vertical"
        initialValues={{ valid_from: dayjs() }}
      >
        <Space.Compact block>
          <Form.Item
            name="kind"
            label={t("consent.admin.col_kind")}
            rules={[{ required: true }]}
            style={{ flex: 1 }}
          >
            <Select options={kindOptions} placeholder="privacy / sepa / …" />
          </Form.Item>
          <Form.Item
            name="version"
            label={t("consent.admin.col_version")}
            rules={[{ required: true, max: 40 }]}
            style={{ flex: 1, marginLeft: 8 }}
          >
            <Input placeholder="2026-05-20 / 3.1 / …" />
          </Form.Item>
        </Space.Compact>

        <Form.Item
          name="title"
          label={t("consent.admin.col_title")}
          rules={[{ max: 200 }]}
        >
          <Input placeholder={t("consent.admin.title_placeholder")} />
        </Form.Item>

        <Form.Item
          name="valid_from"
          label={t("consent.admin.col_effective_from")}
          rules={[{ required: true }]}
        >
          <DatePicker style={{ width: "100%" }} format={dateFormat} />
        </Form.Item>

        <Form.Item
          name="body"
          label={t("consent.admin.body_label")}
          rules={[{ required: true }]}
        >
          <ReactQuill theme="snow" modules={QUILL_MODULES} />
        </Form.Item>
      </Form>

      {mode === "create" && (
        <Alert
          type="info"
          showIcon
          style={{ marginTop: 8 }}
          message={t("consent.admin.append_only_notice")}
        />
      )}
    </Modal>
  );
}
