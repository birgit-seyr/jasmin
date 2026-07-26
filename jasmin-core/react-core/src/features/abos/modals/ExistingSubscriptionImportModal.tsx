import { Alert, Card, Modal, Space, Steps, Table, Typography } from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import DownloadCsvTemplateButton from "@shared/ui/DownloadCsvTemplateButton";

const { Paragraph, Text } = Typography;

interface ExistingSubscriptionImportModalProps {
  open: boolean;
  onClose: () => void;
  /** Tenant ``allow_upload_for_data_lists`` — gates the CSV upload/validate. */
  uploadAllowed: boolean;
  /** Refetch the abos page after a successful (partial or full) import. */
  onUploadSuccess?: () => void;
}

/**
 * Onboarding modal for a tenant that already has members + subscriptions
 * elsewhere. Shows the STAGED import order (reference data → members →
 * subscriptions) and, for subscriptions, the natural-key columns + a
 * template / validate / import affordance.
 *
 * Subscriptions import as unconfirmed DRAFTS — the office confirms them
 * afterwards (the normal flow), which is where deliveries + charges + capacity
 * checks correctly happen. Opened from the bottom of the Abos page.
 */
export default function ExistingSubscriptionImportModal({
  open,
  onClose,
  uploadAllowed,
  onUploadSuccess,
}: ExistingSubscriptionImportModalProps) {
  const { t } = useTranslation();

  // Columns for the subscription CSV template (drives the 3-row download +
  // the upload's ``model_name``). Natural keys — never DB ids.
  const subscriptionColumns = [
    {
      dataIndex: "member_number",
      title: t("onboarding.sub_col.member_number"),
      inputType: "integer",
    },
    {
      dataIndex: "share_type",
      title: t("onboarding.sub_col.share_type"),
      inputType: "text",
    },
    {
      dataIndex: "size",
      title: t("onboarding.sub_col.size"),
      inputType: "text",
    },
    {
      dataIndex: "payment_cycle",
      title: t("onboarding.sub_col.payment_cycle"),
      inputType: "text",
    },
    {
      dataIndex: "delivery_station",
      title: t("onboarding.sub_col.delivery_station"),
      inputType: "text",
    },
    {
      dataIndex: "delivery_day",
      title: t("onboarding.sub_col.delivery_day"),
      inputType: "integer",
    },
    {
      dataIndex: "valid_from",
      title: t("onboarding.sub_col.valid_from"),
      inputType: "date",
    },
    {
      dataIndex: "valid_until",
      title: t("onboarding.sub_col.valid_until"),
      inputType: "date",
    },
    {
      dataIndex: "quantity",
      title: t("onboarding.sub_col.quantity"),
      inputType: "integer",
    },
    {
      dataIndex: "price_per_delivery",
      title: t("onboarding.sub_col.price_per_delivery"),
      inputType: "decimal2",
    },
    {
      dataIndex: "is_trial",
      title: t("onboarding.sub_col.is_trial"),
      inputType: "checkbox",
    },
    {
      dataIndex: "subscription_number",
      title: t("onboarding.sub_col.subscription_number"),
      inputType: "integer",
    },
  ];

  const columnDocRows = [
    { key: "member_number", req: true },
    { key: "share_type", req: true },
    { key: "size", req: true },
    { key: "payment_cycle", req: true },
    { key: "delivery_station", req: false },
    { key: "delivery_day", req: false },
    { key: "valid_from", req: true },
    { key: "valid_until", req: true },
    { key: "quantity", req: false },
    { key: "price_per_delivery", req: false },
    { key: "is_trial", req: false },
    { key: "subscription_number", req: false },
  ];

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={t("onboarding.title")}
      footer={null}
      width={820}
      destroyOnHidden
    >
      <Paragraph type="secondary">{t("onboarding.intro")}</Paragraph>

      <Steps
        direction="vertical"
        current={-1}
        items={[
          {
            title: t("onboarding.stage1.title"),
            description: (
              <Space direction="vertical" size="small">
                <Text>{t("onboarding.stage1.body")}</Text>
                <Space size="small" wrap>
                  <Link to="/configuration/share-type-variations">
                    {t("configuration.share_type_variations")}
                  </Link>
                  <Link to="/configuration/time-management">
                    {t("configuration.delivery_days")}
                  </Link>
                  <Link to="/configuration/payments">
                    {t("configuration.payments")}
                  </Link>
                </Space>
              </Space>
            ),
          },
          {
            title: t("onboarding.stage2.title"),
            description: (
              <Space direction="vertical" size="small">
                <Text>{t("onboarding.stage2.body")}</Text>
                <Link to="/members">{t("onboarding.stage2.link")}</Link>
              </Space>
            ),
          },
          {
            title: t("onboarding.stage3.title"),
            description: (
              <Space direction="vertical" size="small" className="w-full">
                <Text>{t("onboarding.stage3.body")}</Text>
                <Alert
                  type="info"
                  showIcon
                  message={t("onboarding.stage3.drafts_notice")}
                />
                <Card size="small" title={t("onboarding.columns_title")}>
                  <Table
                    size="small"
                    pagination={false}
                    dataSource={columnDocRows}
                    columns={[
                      {
                        title: t("onboarding.col_field"),
                        dataIndex: "key",
                        render: (k: string) => <code>{k}</code>,
                      },
                      {
                        title: t("onboarding.col_required"),
                        dataIndex: "req",
                        render: (r: boolean) =>
                          r ? t("common.yes") : t("common.no"),
                      },
                      {
                        title: t("onboarding.col_meaning"),
                        dataIndex: "key",
                        key: "meaning",
                        render: (k: string) => t(`onboarding.sub_help.${k}`),
                      },
                    ]}
                  />
                  <div style={{ marginTop: 12 }}>
                    {uploadAllowed ? (
                      <DownloadCsvTemplateButton
                        columns={subscriptionColumns}
                        filename="subscriptions_template.csv"
                        modelName="subscription"
                        allowDryRun
                        onUploadSuccess={onUploadSuccess}
                        onImported={onClose}
                      />
                    ) : (
                      <Text type="secondary">
                        {t("onboarding.members_upload_disabled")}
                      </Text>
                    )}
                  </div>
                </Card>
              </Space>
            ),
          },
        ]}
      />
    </Modal>
  );
}
