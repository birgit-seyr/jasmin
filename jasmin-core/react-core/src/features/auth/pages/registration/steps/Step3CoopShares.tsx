import { Button, Flex, Form, InputNumber, Typography } from "antd";
import { useTranslation } from "react-i18next";
import type { StepProps } from "../types";

const { Paragraph } = Typography;

export default function Step3CoopShares({
  data,
  update,
  next,
  back,
}: StepProps) {
  const { t } = useTranslation();
  const [form] = Form.useForm();

  const handleFinish = (values: { coop_shares_count: number }) => {
    update(values);
    next();
  };

  return (
    <>
      <Paragraph>{t("auth.registration.step3.intro")}</Paragraph>

      <Form
        form={form}
        layout="vertical"
        initialValues={{ coop_shares_count: data.coop_shares_count ?? 1 }}
        onFinish={handleFinish}
      >
        <Form.Item
          name="coop_shares_count"
          label={t("auth.registration.step3.shares_label")}
          rules={[
            {
              required: true,
              message: t("auth.registration.step3.shares_required"),
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
              {t("auth.registration.actions.next")}
            </Button>
          </Flex>
        </Form.Item>
      </Form>
    </>
  );
}
