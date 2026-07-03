import { Alert, Button, Flex, Form, Input, Typography } from "antd";
import { Trans, useTranslation } from "react-i18next";
import type { StepProps } from "../types";

const { Paragraph } = Typography;

/**
 * Placeholder verification step. Real implementation will POST the email to
 * the backend, which sends a code; the user enters it here and we verify.
 * For now we accept any non-empty code so the wizard can be walked through.
 */
export default function Step2VerifyEmail({
  data,
  update,
  next,
  back,
}: StepProps) {
  const { t } = useTranslation();
  const [form] = Form.useForm();

  const handleFinish = (values: { code: string }) => {
    update({
      email_verification_code: values.code,
      email_verified: true,
    });
    next();
  };

  return (
    <>
      <Paragraph>
        <Trans
          i18nKey="auth.registration.step2.intro"
          values={{ email: data.email }}
          components={{ 1: <strong /> }}
        />
      </Paragraph>

      <Alert
        type="info"
        showIcon
        message={t("auth.registration.step2.stub_notice")}
        style={{ marginBottom: 16 }}
      />

      <Form
        form={form}
        layout="vertical"
        initialValues={{ code: data.email_verification_code }}
        onFinish={handleFinish}
      >
        <Form.Item
          name="code"
          label={t("auth.registration.step2.code_label")}
          rules={[
            {
              required: true,
              message: t("auth.registration.step2.code_required"),
            },
          ]}
        >
          <Input maxLength={8} />
        </Form.Item>

        <Form.Item>
          <Flex justify="space-between" gap="small">
            <Button onClick={back}>
              {t("auth.registration.actions.back")}
            </Button>
            <Button type="primary" htmlType="submit">
              {t("auth.registration.actions.verify_continue")}
            </Button>
          </Flex>
        </Form.Item>
      </Form>
    </>
  );
}
