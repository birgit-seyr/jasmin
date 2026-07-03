import {
  Alert,
  Button,
  DatePicker,
  Descriptions,
  Divider,
  Flex,
  Form,
  Input,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  useCommissioningMyMemberDataPartialUpdate,
  useCommissioningMyMemberDataRetrieve,
} from "@shared/api/generated/commissioning/commissioning";
import {
  MyMemberDataRead,
  MyDataCoopShare,
} from "@shared/api/generated/models";
import { useDateFormat } from "@hooks/index";
import { notify } from "@shared/utils";
import StoredOrEditField from "./StoredOrEditField";

const { Title, Paragraph } = Typography;

const MEMBER_EDITABLE_FIELDS = [
  "first_name",
  "last_name",
  "company_name",
  "pickup_name",
  "address",
  "zip_code",
  "city",
  "country",
] as const satisfies readonly (keyof MyMemberDataRead)[];

const DATE_FORMAT_WIRE = "YYYY-MM-DD";

/**
 * Member-self-edit surface backed by ``commissioning/my_member_data/``.
 *
 * Layout: Stammdaten (member_number / is_trial / entry_date) on top,
 * then the coop-share holdings, then the editable form (address,
 * payment, IBAN / account_owner via {@link StoredOrEditField}).
 *
 * Encrypted fields are never echoed as plaintext — IBAN and
 * ``account_owner`` come back as ``*_stored`` booleans and an empty
 * input on submit is dropped from the payload so saving the form with
 * the IBAN tab still closed doesn't accidentally clear it.
 */
export default function MemberSection({ onSaved }: { onSaved: () => void }) {
  const { t } = useTranslation();
  const { dateFormat, formatDateWithFallback } = useDateFormat();
  const [form] = Form.useForm();
  const [editingIban, setEditingIban] = useState(false);
  const [editingAccountOwner, setEditingAccountOwner] = useState(false);

  const { data, isLoading, error } = useCommissioningMyMemberDataRetrieve();

  const { mutate, isPending } = useCommissioningMyMemberDataPartialUpdate({
    mutation: {
      onSuccess: () => {
        notify.success(t("profile.saved"));
        setEditingIban(false);
        setEditingAccountOwner(false);
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
  const initialValues: Record<string, unknown> = Object.fromEntries(
    MEMBER_EDITABLE_FIELDS.map((field) => [field, data[field] ?? ""]),
  );
  // ``birth_date`` arrives as ``YYYY-MM-DD``; AntD DatePicker needs
  // a dayjs instance, so convert at the edges.
  initialValues.birth_date = data.birth_date
    ? dayjs(data.birth_date)
    : null;

  const onFinish = (values: Record<string, unknown>) => {
    // Strip empty IBAN/account_owner unless the user explicitly opened
    // the edit — prevents "save" from clearing a previously-set value
    // the user can't currently see.
    const payload: Record<string, unknown> = { ...values };
    if (!editingIban) delete payload.iban;
    if (!editingAccountOwner) delete payload.account_owner;
    payload.birth_date = values.birth_date
      ? (values.birth_date as dayjs.Dayjs).format(DATE_FORMAT_WIRE)
      : null;
    mutate({ data: payload as never });
  };

  return (
    <div>
      <Title level={5} style={{ marginTop: 0 }}>
        {t("profile.member_facts")}
      </Title>
      <Descriptions column={1} bordered size="small">
        <Descriptions.Item label={t("gdpr.member_number")}>
          {data.member_number ?? "-"}
        </Descriptions.Item>
        {data.is_trial ? (
          <Descriptions.Item label={t("profile.is_trial")}>
            {t("common.yes")}
          </Descriptions.Item>
        ) : null}
        <Descriptions.Item label={t("profile.entry_date")}>
          {formatDateWithFallback(data.entry_date)}
        </Descriptions.Item>
      </Descriptions>
      <Divider />

      <Title level={5} style={{ marginTop: 16 }}>
        {t("profile.coop_shares")}
      </Title>
      <CoopSharesList shares={data.coop_shares ?? []} />

      <Divider />

      <Title level={5}>{t("profile.member_data")}</Title>
      <Form
        form={form}
        layout="vertical"
        initialValues={initialValues}
        onFinish={onFinish}
        // Force a remount when the backend data lands so the form
        // picks up server values on first render.
        key={JSON.stringify(initialValues)}
      >
        <Form.Item name="first_name" label={t("profile.first_name")}>
          <Input />
        </Form.Item>
        <Form.Item name="last_name" label={t("profile.last_name")}>
          <Input />
        </Form.Item>
        <Form.Item
          name="company_name"
          label={t("profile.company_name")}
        >
          <Input />
        </Form.Item>
        <Form.Item
          name="pickup_name"
          label={t("profile.pickup_name")}
          extra={t("profile.pickup_name_help")}
        >
          <Input />
        </Form.Item>
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
            style={{ flex: 1 }}
          >
            <Input />
          </Form.Item>
        </Flex>
        <Form.Item name="country" label={t("profile.country")}>
          <Input />
        </Form.Item>
        <Form.Item
          name="birth_date"
          label={t("profile.birth_date")}
        >
          <DatePicker style={{ width: "100%" }} format={dateFormat} />
        </Form.Item>

        <StoredOrEditField
          name="iban"
          label="IBAN"
          stored={Boolean(data.iban_stored)}
          editing={editingIban}
          onStartEdit={() => setEditingIban(true)}
          onCancelEdit={() => {
            form.setFieldValue("iban", "");
            setEditingIban(false);
          }}
        />
        <StoredOrEditField
          name="account_owner"
          label={t("profile.account_owner")}
          stored={Boolean(data.account_owner_stored)}
          editing={editingAccountOwner}
          onStartEdit={() => setEditingAccountOwner(true)}
          onCancelEdit={() => {
            form.setFieldValue("account_owner", "");
            setEditingAccountOwner(false);
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
    </div>
  );
}

function CoopSharesList({ shares }: { shares: readonly MyDataCoopShare[] }) {
  const { t } = useTranslation();
  const { formatDateWithFallback } = useDateFormat();
  if (!shares.length) {
    return (
      <Paragraph type="secondary">
        {t("profile.no_coop_shares")}
      </Paragraph>
    );
  }
  return (
    <Descriptions column={1} bordered size="small">
      {shares.map((share) => (
        <Descriptions.Item
          key={share.id}
          label={`${share.amount_of_coop_shares ?? "-"} ${t("profile.shares_short")}`}
        >
          <Space size="large">
            <span>
              {t("profile.due_date")}:{" "}
              {formatDateWithFallback(share.due_date)}
            </span>
            <span>
              {t("profile.paid_at")}:{" "}
              {share.paid_at ? (
                formatDateWithFallback(share.paid_at)
              ) : (
                <Tag color="orange">{t("profile.unpaid")}</Tag>
              )}
            </span>
          </Space>
        </Descriptions.Item>
      ))}
    </Descriptions>
  );
}
