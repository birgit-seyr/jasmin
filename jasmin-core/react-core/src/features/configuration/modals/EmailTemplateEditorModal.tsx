import { ReloadOutlined, SendOutlined } from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  Col,
  Collapse,
  Input,
  Modal,
  Row,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import ReactQuill from "react-quill-new";
import "react-quill-new/dist/quill.snow.css";

import type { EmailTemplateUpdate, TestSend } from "@shared/api/generated/models";
import {
  getNotificationsEmailTemplatesListQueryKey,
  getNotificationsEmailTemplatesRetrieveQueryKey,
  useNotificationsEmailTemplatesPartialUpdate,
  useNotificationsEmailTemplatesReset,
  useNotificationsEmailTemplatesRetrieve,
  useNotificationsEmailTemplatesTestSend,
} from "@shared/api/generated/notifications/notifications";
import {
  chipsToPlaceholders,
  chipsToPlainText,
  placeholdersToChips,
  plainTextToChips,
} from "@shared/quill/VariableBlot";
import { notify } from "@shared/utils";

const { Text, Paragraph } = Typography;

const QUILL_MODULES = {
  toolbar: [
    [{ header: [1, 2, 3, false] }],
    ["bold", "italic", "underline"],
    [{ list: "ordered" }, { list: "bullet" }],
    [{ color: [] }, { background: [] }],
    ["link"],
    ["clean"],
  ],
};

const QUILL_FORMATS = [
  "header",
  "bold",
  "italic",
  "underline",
  "list",
  "bullet",
  "color",
  "background",
  "link",
  "tplVar",
];

// Subject line: no toolbar, only the variable chip blot, Enter disabled.
const SUBJECT_MODULES = {
  toolbar: false,
  keyboard: {
    bindings: {
      enter: { key: 13, handler: () => false },
      shift_enter: { key: 13, shiftKey: true, handler: () => false },
    },
  },
};
const SUBJECT_FORMATS = ["tplVar"];

interface Props {
  slug: string | null;
  onClose: () => void;
}

export default function EmailTemplateEditorModal({ slug, onClose }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [subjectHtml, setSubjectHtml] = useState("");
  const [bodyHtml, setBodyHtml] = useState("");
  const [testRecipient, setTestRecipient] = useState("");
  const [activeField, setActiveField] = useState<"subject" | "body_html">(
    "body_html",
  );

  const subjectQuillRef = useRef<ReactQuill | null>(null);
  const quillRef = useRef<ReactQuill | null>(null);

  const { data: detail, isLoading } = useNotificationsEmailTemplatesRetrieve(
    slug ?? "",
    undefined,
    {
      query: {
        // Modal stays mounted across openings — disable when no slug
        // and don't keep stale detail data between two different
        // templates.
        enabled: !!slug,
        staleTime: 0,
        gcTime: 0,
      },
    },
  );

  const labelByName = useMemo(() => {
    const map: Record<string, string> = {};
    detail?.variables?.forEach((v) => {
      map[v.name] = v.label;
    });
    return map;
  }, [detail]);

  // Rendered reference copy of the shipped default — the same content the
  // tenant would get if they hit "Reset to default". Server returns it
  // already resolved to the tenant's language (``_tenant_language()`` in
  // apps/notifications/viewsets.py), so this stays in sync with whatever
  // language the email is actually sent in.
  const defaultSubjectChips = useMemo(
    () => plainTextToChips(detail?.default_subject ?? "", labelByName),
    [detail?.default_subject, labelByName],
  );
  const defaultBodyChips = useMemo(
    () => placeholdersToChips(detail?.default_body_html ?? "", labelByName),
    [detail?.default_body_html, labelByName],
  );

  useEffect(() => {
    // Reset all local state whenever the slug changes (or modal closes)
    // so a freshly opened modal never shows the previous template's content.
    setSubjectHtml("");
    setBodyHtml("");
    setTestRecipient("");
  }, [slug]);

  useEffect(() => {
    if (detail) {
      setSubjectHtml(plainTextToChips(detail.subject, labelByName));
      setBodyHtml(placeholdersToChips(detail.body_html, labelByName));
    }
  }, [detail, labelByName]);

  const buildPayload = (): EmailTemplateUpdate => ({
    subject: chipsToPlainText(subjectHtml),
    body_html: chipsToPlaceholders(bodyHtml),
    body_text: detail?.body_text ?? "",
  });

  const saveMutation = useNotificationsEmailTemplatesPartialUpdate({
    mutation: {
      onSuccess: (data) => {
        notify.success(t("email_templates.saved"));
        queryClient.setQueryData(
          getNotificationsEmailTemplatesRetrieveQueryKey(slug!),
          data,
        );
        queryClient.invalidateQueries({
          queryKey: getNotificationsEmailTemplatesListQueryKey(),
        });
      },
      onError: () =>
        notify.error(
          t("email_templates.save_error"),
        ),
    },
  });

  const resetMutation = useNotificationsEmailTemplatesReset({
    mutation: {
      onSuccess: (data) => {
        setSubjectHtml(plainTextToChips(data.subject, labelByName));
        setBodyHtml(placeholdersToChips(data.body_html, labelByName));
        queryClient.setQueryData(
          getNotificationsEmailTemplatesRetrieveQueryKey(slug!),
          data,
        );
        queryClient.invalidateQueries({
          queryKey: getNotificationsEmailTemplatesListQueryKey(),
        });
        notify.success(
          t("email_templates.reset_done"),
        );
      },
      onError: () =>
        notify.error(
          t("email_templates.reset_error"),
        ),
    },
  });

  const testMutation = useNotificationsEmailTemplatesTestSend({
    mutation: {
      onSuccess: (data) => notify.success(data.detail),
      onError: () =>
        notify.error(
          t("email_templates.test_error"),
        ),
    },
  });

  const insertVariable = (name: string, label: string) => {
    const ref = activeField === "subject" ? subjectQuillRef : quillRef;
    const quill = ref.current?.getEditor();
    if (!quill) return;
    const range = quill.getSelection(true);
    const index = range ? range.index : quill.getLength();
    quill.insertEmbed(index, "tplVar", { name, label }, "user");
    quill.setSelection(index + 1, 0, "user");
  };

  // Label + description in the registry are hardcoded German. Look up
  // a per-slug translation first, fall back to the backend value if no
  // override exists. Dots in the slug are the i18next nesting
  // separator, so substitute "_" to keep the key flat.
  const slugKey = detail ? detail.slug.replace(/\./g, "_") : "";
  const localizedLabel = detail
    ? t(`email_templates.label.${slugKey}`, { defaultValue: detail.label })
    : "";
  const localizedDescription = detail
    ? t(`email_templates.description.${slugKey}`, {
        defaultValue: detail.description,
      })
    : "";

  return (
    <Modal
      open={!!slug}
      onCancel={onClose}
      destroyOnHidden
      width={1100}
      title={
        detail
          ? `${localizedLabel} (${detail.slug})`
          : t("email_templates.editor")
      }
      footer={[
        <Button
          key="reset"
          icon={<ReloadOutlined />}
          danger
          disabled={!detail?.is_customized}
          loading={resetMutation.isPending}
          onClick={() => slug && resetMutation.mutate({ slug })}
        >
          {t("email_templates.reset_to_default")}
        </Button>,
        <Button key="cancel" onClick={onClose}>
          {t("common.cancel")}
        </Button>,
        <Button
          key="save"
          type="primary"
          loading={saveMutation.isPending}
          onClick={() =>
            slug &&
            saveMutation.mutate({ slug, data: buildPayload() })
          }
        >
          {t("common.save")}
        </Button>,
      ]}
    >
      {isLoading || !detail ? (
        <Spin />
      ) : (
        <Row gutter={16}>
          <Col span={16}>
            <Space direction="vertical" size="middle" className="w-full">
              <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                {localizedDescription}
              </Paragraph>

              <div className="email-tpl-subject">
                <Text strong>{t("email_templates.subject")}</Text>
                <ReactQuill
                  ref={subjectQuillRef}
                  theme="snow"
                  value={subjectHtml}
                  onChange={setSubjectHtml}
                  onFocus={() => setActiveField("subject")}
                  modules={SUBJECT_MODULES}
                  formats={SUBJECT_FORMATS}
                  placeholder={detail.default_subject}
                />
              </div>

              <div className="email-tpl-editor">
                <ReactQuill
                  ref={quillRef}
                  theme="snow"
                  value={bodyHtml}
                  onChange={setBodyHtml}
                  onFocus={() => setActiveField("body_html")}
                  modules={QUILL_MODULES}
                  formats={QUILL_FORMATS}
                  style={{ background: "var(--color-bg-base)", marginTop: 4 }}
                />
              </div>

              <Collapse
                size="small"
                items={[
                  {
                    key: "default",
                    label: (
                      <Space size={8}>
                        <Text strong>
                          {t("email_templates.show_default")}
                        </Text>
                        <Tag>{detail.language.toUpperCase()}</Tag>
                      </Space>
                    ),
                    children: (
                      <Space
                        direction="vertical"
                        size="small"
                        className="w-full"
                      >
                        <Paragraph
                          type="secondary"
                          style={{ marginBottom: 4, fontSize: 12 }}
                        >
                          {t("email_templates.default_reference_help")}
                        </Paragraph>

                        <div className="email-tpl-default-subject">
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            {t("email_templates.subject")}
                          </Text>
                          <ReactQuill
                            theme="snow"
                            value={defaultSubjectChips}
                            readOnly
                            modules={{ toolbar: false }}
                            formats={SUBJECT_FORMATS}
                          />
                        </div>

                        <div className="email-tpl-default-body">
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            {t("email_templates.body")}
                          </Text>
                          <ReactQuill
                            theme="snow"
                            value={defaultBodyChips}
                            readOnly
                            modules={{ toolbar: false }}
                            formats={QUILL_FORMATS}
                            style={{ background: "var(--color-bg-elevated)", marginTop: 4 }}
                          />
                        </div>
                      </Space>
                    ),
                  },
                ]}
              />

              <Space>
                <Input
                  placeholder={t("email_templates.test_recipient")}
                  value={testRecipient}
                  onChange={(e) => setTestRecipient(e.target.value)}
                  style={{ width: 280 }}
                />
                <Button
                  icon={<SendOutlined />}
                  onClick={() => {
                    if (!slug) return;
                    const body: TestSend = testRecipient
                      ? { recipient: testRecipient }
                      : {};
                    testMutation.mutate({ slug, data: body });
                  }}
                  loading={testMutation.isPending}
                >
                  {t("email_templates.send_test")}
                </Button>
              </Space>
            </Space>
          </Col>

          <Col span={8}>
            <Card
              size="small"
              title={t("email_templates.variables")}
            >
              <Paragraph
                type="secondary"
                style={{ marginBottom: 8, fontSize: 12 }}
              >
                {t("email_templates.variables_help")}
              </Paragraph>
              <Space wrap size={[6, 6]}>
                {detail.variables.map((v) => (
                  <Tooltip
                    key={v.name}
                    title={
                      <span>
                        {v.description}
                        {v.description ? <br /> : null}
                        <code
                          style={{ fontSize: 11 }}
                        >{`{{ ${v.name} }}`}</code>
                      </span>
                    }
                  >
                    <Tag
                      color="geekblue"
                      style={{ cursor: "pointer", userSelect: "none" }}
                      onClick={() => insertVariable(v.name, v.label)}
                    >
                      {v.label}
                    </Tag>
                  </Tooltip>
                ))}
              </Space>
            </Card>
          </Col>
        </Row>
      )}
    </Modal>
  );
}
