import { Button, Flex, Form, Input, Typography } from "antd";
import { useTranslation } from "react-i18next";
import type { StepProps } from "../types";

const { Paragraph } = Typography;

interface Values {
  first_name: string;
  last_name: string;
  email: string;
  address?: string;
  zip_code?: string;
  city?: string;
  country?: string;
}

/**
 * Step 4 — the applicant's identity + (optional) address. Collected AFTER the
 * choices/consents so the email we then verify is the last thing entered.
 */
export default function StepYourDetails({ data, update, next, back }: StepProps) {
  const { t } = useTranslation();
  const [form] = Form.useForm<Values>();

  const handleFinish = (values: Values) => {
    update(values);
    next();
  };

  return (
    <>
      <Paragraph>{t("auth.registration.details.intro")}</Paragraph>
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          first_name: data.first_name,
          last_name: data.last_name,
          email: data.email,
          address: data.address,
          zip_code: data.zip_code,
          city: data.city,
          country: data.country,
        }}
        onFinish={handleFinish}
      >
        <Flex gap="small">
          <Form.Item
            name="first_name"
            label={t("auth.registration.details.first_name")}
            rules={[
              {
                required: true,
                message: t("auth.registration.details.first_name_required"),
              },
            ]}
            style={{ flex: 1 }}
          >
            <Input autoComplete="given-name" />
          </Form.Item>
          <Form.Item
            name="last_name"
            label={t("auth.registration.details.last_name")}
            rules={[
              {
                required: true,
                message: t("auth.registration.details.last_name_required"),
              },
            ]}
            style={{ flex: 1 }}
          >
            <Input autoComplete="family-name" />
          </Form.Item>
        </Flex>

        <Form.Item
          name="email"
          label={t("auth.registration.details.email")}
          rules={[
            {
              required: true,
              message: t("auth.registration.details.email_required"),
            },
            {
              type: "email",
              message: t("auth.registration.details.email_invalid"),
            },
          ]}
        >
          <Input autoComplete="email" />
        </Form.Item>

        <Form.Item
          name="address"
          label={t("auth.registration.details.address")}
        >
          <Input autoComplete="street-address" />
        </Form.Item>

        <Flex gap="small">
          <Form.Item
            name="zip_code"
            label={t("auth.registration.details.zip_code")}
            style={{ width: 140 }}
          >
            <Input autoComplete="postal-code" />
          </Form.Item>
          <Form.Item
            name="city"
            label={t("auth.registration.details.city")}
            style={{ flex: 1 }}
          >
            <Input autoComplete="address-level2" />
          </Form.Item>
        </Flex>

        <Form.Item
          name="country"
          label={t("auth.registration.details.country")}
        >
          <Input autoComplete="country-name" />
        </Form.Item>

        <Flex justify="space-between">
          <Button onClick={back}>{t("auth.registration.actions.back")}</Button>
          <Button type="primary" htmlType="submit">
            {t("auth.registration.actions.next")}
          </Button>
        </Flex>
      </Form>
    </>
  );
}
