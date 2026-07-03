import { Button, Flex, Form, Input } from "antd";
import { useTranslation } from "react-i18next";
import type { StepProps } from "../types";

/**
 * Step 6 — set the password the applicant will use to sign in once
 * office approves them. Collected near the end (rather than in Step 1)
 * so it sits next to the final submit and the user understands they're
 * setting up an account, not just leaving contact info.
 *
 * The backend (``register_public_applicant``) runs ``validate_password``
 * with the project's full validator chain (min 12 chars, zxcvbn ≥3,
 * not all-numeric, no user-attribute similarity). Client-side we only
 * enforce the cheap checks; the server is the source of truth.
 */
const MIN_LENGTH = 12;

export default function Step6Password({ data, update, next, back }: StepProps) {
  const { t } = useTranslation();
  const [form] = Form.useForm();

  const handleFinish = (values: { password: string; password_confirm: string }) => {
    if (values.password !== values.password_confirm) {
      form.setFields([
        {
          name: "password_confirm",
          errors: [
            t("auth.registration.step6.passwords_must_match"),
          ],
        },
      ]);
      return;
    }
    update({ password: values.password });
    next();
  };

  return (
    <Form
      form={form}
      layout="vertical"
      initialValues={{ password: data.password ?? "" }}
      onFinish={handleFinish}
    >
      <Form.Item
        name="password"
        label={t("auth.registration.step6.password")}
        rules={[
          {
            required: true,
            message: t("auth.registration.step6.password_required"),
          },
          {
            min: MIN_LENGTH,
            message: t(
              "auth.registration.step6.password_too_short",
              { n: MIN_LENGTH },
            ),
          },
        ]}
      >
        <Input.Password autoComplete="new-password" />
      </Form.Item>

      <Form.Item
        name="password_confirm"
        label={t("auth.registration.step6.password_confirm")}
        dependencies={["password"]}
        rules={[
          {
            required: true,
            message: t("auth.registration.step6.password_confirm_required"),
          },
        ]}
      >
        <Input.Password autoComplete="new-password" />
      </Form.Item>

      <Form.Item>
        <Flex justify="space-between" gap="small">
          <Button onClick={back}>
            {t("auth.registration.actions.back")}
          </Button>
          <Button type="primary" htmlType="submit">
            {t("auth.registration.actions.next")}
          </Button>
        </Flex>
      </Form.Item>
    </Form>
  );
}
