import { SendOutlined } from "@ant-design/icons";
import { Form, Modal, Select, Typography } from "antd";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";

const { Text } = Typography;

interface TestEmailModalProps {
  open: boolean;
  onCancel: () => void;
  onSend: (email: string) => void;
  sending: boolean;
  allowedEmails: string[];
  defaultEmail?: string;
}

export default function TestEmailModal({
  open,
  onCancel,
  onSend,
  sending,
  allowedEmails,
  defaultEmail,
}: TestEmailModalProps) {
  const [form] = Form.useForm();
  const { t } = useTranslation();

  useEffect(() => {
    if (open) {
      const fallback = allowedEmails[0] || "";
      form.setFieldsValue({
        to_email:
          defaultEmail && allowedEmails.includes(defaultEmail)
            ? defaultEmail
            : fallback,
      });
    }
  }, [open, defaultEmail, allowedEmails, form]);

  return (
    <Modal
      title={t("email_config.test_title")}
      open={open}
      onCancel={onCancel}
      onOk={() => {
        form.validateFields().then((values) => {
          onSend(values.to_email);
        });
      }}
      okText={t("email_config.send_test")}
      okButtonProps={{ icon: <SendOutlined />, loading: sending }}
      cancelText={t("common.cancel")}
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="to_email"
          label={t("email_config.test_recipient")}
          rules={[
            {
              required: true,
              message: t("email_config.email_required"),
            },
          ]}
        >
          {/* Backend-enforced allowlist: only addresses belonging to
              this configuration (your account, tenant contact,
              sender / reply-to) are accepted — so offer exactly those
              instead of a free-text field. */}
          <Select
            options={allowedEmails.map((address) => ({
              value: address,
              label: address,
            }))}
            placeholder={t("email_config.test_recipient_placeholder")}
          />
        </Form.Item>
        <Text type="secondary">
          {t("email_config.test_description_restricted")}
        </Text>
      </Form>
    </Modal>
  );
}
