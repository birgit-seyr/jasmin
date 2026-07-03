import {
  Alert,
  Button,
  Descriptions,
  Divider,
  Flex,
  Form,
  Input,
  Spin,
  Typography,
} from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  useCommissioningMyCustomerDataPartialUpdate,
  useCommissioningMyCustomerDataRetrieve,
} from "@shared/api/generated/commissioning/commissioning";
import type { MyCustomerDataRead } from "@shared/api/generated/models";
import { notify } from "@shared/utils";
import StoredOrEditField from "./StoredOrEditField";

const { Title } = Typography;

const CUSTOMER_EDITABLE_FIELDS = [
  "company_name",
  "first_name",
  "last_name",
  "address",
  "zip_code",
  "city",
  "country",
  "email",
  "email_2",
  "email_3",
  "order_email",
  "phone",
  "phone_2",
  "phone_3",
  "uid",
] as const;

/**
 * Customer-self-edit surface backed by
 * ``commissioning/my_customer_data/``. Edits land on the linked
 * ``ContactEntity`` — Reseller-level fields (customer_number,
 * invoice_*, *_via_email channel flags) stay office-only and
 * appear here only as read-only "Stammdaten".
 *
 * IBAN is the only encrypted field on this surface; treatment matches
 * the member side ({@link StoredOrEditField}).
 */
export default function CustomerSection({ onSaved }: { onSaved: () => void }) {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [editingIban, setEditingIban] = useState(false);

  const { data, isLoading, error } = useCommissioningMyCustomerDataRetrieve();

  const { mutate, isPending } = useCommissioningMyCustomerDataPartialUpdate({
    mutation: {
      onSuccess: () => {
        notify.success(t("profile.saved"));
        setEditingIban(false);
        onSaved();
      },
      onError: () => {
        notify.error(t("profile.save_error"));
      },
    },
  });

  if (isLoading) return <Spin />;
  if (error || !data) {
    return (
      <Alert
        type="error"
        message={t("profile.load_error")}
      />
    );
  }

  const c = data;
  const initialValues = Object.fromEntries(
    CUSTOMER_EDITABLE_FIELDS.map((field: keyof MyCustomerDataRead) => [
      field,
      (c[field] ?? "") as string,
    ]),
  );

  const onFinish = (values: Record<string, string>) => {
    const payload: Record<string, string> = { ...values };
    if (!editingIban) delete payload.iban;
    mutate({ data: payload as never });
  };

  return (
    <div>
      <Title level={5} style={{ marginTop: 0 }}>
        {t("profile.customer_data")}
      </Title>

      <Form
        form={form}
        layout="vertical"
        initialValues={initialValues}
        onFinish={onFinish}
        key={JSON.stringify(initialValues)}
      >
        <Form.Item
          name="company_name"
          label={t("profile.company_name")}
        >
          <Input />
        </Form.Item>
        <Flex gap="middle">
          <Form.Item
            name="first_name"
            label={t("profile.first_name")}
            style={{ flex: 1 }}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="last_name"
            label={t("profile.last_name")}
            style={{ flex: 1 }}
          >
            <Input />
          </Form.Item>
        </Flex>

        <Form.Item name="address" label={t("profile.address")}>
          <Input />
        </Form.Item>
        <Flex gap="middle">
          <Form.Item
            name="zip_code"
            label={t("profile.zip_code")}
            style={{ flex: 1 }}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="city"
            label={t("profile.city")}
            style={{ flex: 2 }}
          >
            <Input />
          </Form.Item>
        </Flex>
        <Form.Item name="country" label={t("profile.country")}>
          <Input />
        </Form.Item>

        <Title level={5}>
          {t("profile.email_addresses")}
        </Title>
        <Form.Item
          name="email"
          label={t("profile.email")}
          rules={[{ type: "email" }]}
        >
          <Input />
        </Form.Item>
        <Form.Item
          name="email_2"
          label={t("profile.email_2")}
        >
          <Input />
        </Form.Item>
        <Form.Item
          name="email_3"
          label={t("profile.email_3")}
        >
          <Input />
        </Form.Item>
        <Form.Item
          name="order_email"
          label={t("profile.order_email")}
          rules={[{ type: "email" }]}
        >
          <Input />
        </Form.Item>

        <Title level={5}>{t("profile.phone_numbers")}</Title>
        <Form.Item name="phone" label={t("profile.phone")}>
          <Input />
        </Form.Item>
        <Form.Item name="phone_2" label={t("profile.phone_2")}>
          <Input />
        </Form.Item>
        <Form.Item name="phone_3" label={t("profile.phone_3")}>
          <Input />
        </Form.Item>

        <Form.Item name="uid" label={t("gdpr.uid")}>
          <Input />
        </Form.Item>

        <StoredOrEditField
          name="iban"
          label="IBAN"
          stored={Boolean(c.iban_stored)}
          editing={editingIban}
          onStartEdit={() => setEditingIban(true)}
          onCancelEdit={() => {
            form.setFieldValue("iban", "");
            setEditingIban(false);
          }}
        />

        <Form.Item>
          <Button
            type="primary"
            htmlType="submit"
            loading={isPending}
            style={{ background: "var(--color-primary-hover)" }}
          >
            {t("common.save")}
          </Button>
        </Form.Item>
      </Form>

      <Divider />
      <Title level={5}>{t("profile.customer_facts")}</Title>
      <Descriptions column={1} bordered size="small">
        <Descriptions.Item label={t("gdpr.customer_number")}>
          {c.customer_number ?? "-"}
        </Descriptions.Item>
      </Descriptions>
    </div>
  );
}
