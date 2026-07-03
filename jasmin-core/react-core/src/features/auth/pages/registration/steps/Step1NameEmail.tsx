import { Button, Flex, Form, Input } from "antd";
import { useTranslation } from "react-i18next";
import type { StepProps } from "../types";

export default function Step1NameEmail({ data, update, next }: StepProps) {
  const { t } = useTranslation();
  const [form] = Form.useForm();

  const handleFinish = (values: {
    first_name: string;
    last_name: string;
    email: string;
  }) => {
    update(values);
    next();
  };

  return (
    <Form
      form={form}
      layout="vertical"
      initialValues={{
        first_name: data.first_name,
        last_name: data.last_name,
        email: data.email,
      }}
      onFinish={handleFinish}
    >
      <Form.Item
        name="first_name"
        label={t("auth.registration.step1.first_name")}
        rules={[
          {
            required: true,
            message: t("auth.registration.step1.first_name_required"),
          },
        ]}
      >
        <Input autoComplete="given-name" />
      </Form.Item>

      <Form.Item
        name="last_name"
        label={t("auth.registration.step1.last_name")}
        rules={[
          {
            required: true,
            message: t("auth.registration.step1.last_name_required"),
          },
        ]}
      >
        <Input autoComplete="family-name" />
      </Form.Item>

      <Form.Item
        name="email"
        label={t("auth.registration.step1.email")}
        rules={[
          {
            required: true,
            message: t("auth.registration.step1.email_required"),
          },
          {
            type: "email",
            message: t("auth.registration.step1.email_invalid"),
          },
        ]}
      >
        <Input autoComplete="email" />
      </Form.Item>

      <Form.Item>
        <Flex justify="flex-end" gap="small">
          <Button type="primary" htmlType="submit">
            {t("auth.registration.actions.next")}
          </Button>
        </Flex>
      </Form.Item>
    </Form>
  );
}
