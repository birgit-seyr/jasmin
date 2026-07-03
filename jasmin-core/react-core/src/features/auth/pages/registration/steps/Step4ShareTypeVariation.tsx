import { Button, Flex, Form, InputNumber, Select, Typography } from "antd";
import { useTranslation } from "react-i18next";
import type { StepProps } from "../types";

const { Paragraph } = Typography;

/**
 * Placeholder for the share-type variation order step. The real version
 * will fetch available variations from the backend (per current contract
 * period) and render them as cards. For now we ship a hard-coded select
 * so the wizard can be walked through end-to-end.
 */
export default function Step4ShareTypeVariation({
  data,
  update,
  next,
  back,
}: StepProps) {
  const { t } = useTranslation();
  const [form] = Form.useForm();

  const handleFinish = (values: {
    share_type_variation_id: string;
    quantity: number;
  }) => {
    update(values);
    next();
  };

  return (
    <>
      <Paragraph>{t("auth.registration.step4.intro")}</Paragraph>

      <Form
        form={form}
        layout="vertical"
        initialValues={{
          share_type_variation_id: data.share_type_variation_id,
          quantity: data.quantity ?? 1,
        }}
        onFinish={handleFinish}
      >
        <Form.Item
          name="share_type_variation_id"
          label={t("auth.registration.step4.variation_label")}
          rules={[
            {
              required: true,
              message: t("auth.registration.step4.variation_required"),
            },
          ]}
        >
          <Select
            placeholder={t("auth.registration.step4.variation_placeholder")}
            options={[
              {
                label: t("auth.registration.step4.variations.small"),
                value: "small",
              },
              {
                label: t("auth.registration.step4.variations.medium"),
                value: "medium",
              },
              {
                label: t("auth.registration.step4.variations.large"),
                value: "large",
              },
            ]}
          />
        </Form.Item>

        <Form.Item
          name="quantity"
          label={t("auth.registration.step4.quantity_label")}
          rules={[
            {
              required: true,
              message: t("auth.registration.step4.quantity_required"),
            },
          ]}
        >
          <InputNumber min={1} max={10} className="w-full" />
        </Form.Item>

        <Form.Item>
          <Flex justify="space-between" gap="small">
            <Button onClick={back}>
              {t("auth.registration.actions.back")}
            </Button>
            <Button type="primary" htmlType="submit">
              {t("auth.registration.actions.review")}
            </Button>
          </Flex>
        </Form.Item>
      </Form>
    </>
  );
}
