import { Alert, Card, Modal, Space, Table, Typography } from "antd";
import { useTranslation } from "react-i18next";
import DownloadCsvTemplateButton from "@shared/ui/DownloadCsvTemplateButton";

const { Paragraph, Text } = Typography;

interface CoopShareImportModalProps {
  open: boolean;
  onClose: () => void;
  /** Tenant ``allow_upload_for_data_lists`` — gates the CSV upload/validate. */
  uploadAllowed: boolean;
  /** Refetch the page after a successful (partial or full) import. */
  onUploadSuccess?: () => void;
}

/**
 * Onboarding modal for bulk-importing members' EXISTING cooperative shares
 * (GenG equity). Each row resolves a member by member number and creates an
 * **unconfirmed** ``CoopShare`` — the office confirms it afterwards (the normal
 * flow, where the min/max equity window is enforced for confirmed members).
 * Opened from the bottom of the members page.
 */
export default function CoopShareImportModal({
  open,
  onClose,
  uploadAllowed,
  onUploadSuccess,
}: CoopShareImportModalProps) {
  const { t } = useTranslation();

  const columns = [
    {
      dataIndex: "member_number",
      title: t("onboarding.coop_col.member_number"),
      inputType: "integer",
    },
    {
      dataIndex: "amount_of_coop_shares",
      title: t("onboarding.coop_col.amount"),
      inputType: "decimal2",
    },
    {
      dataIndex: "value_one_coop_share",
      title: t("onboarding.coop_col.value_one"),
      inputType: "integer",
    },
    {
      dataIndex: "is_increase",
      title: t("onboarding.coop_col.is_increase"),
      inputType: "checkbox",
    },
    {
      dataIndex: "note",
      title: t("onboarding.coop_col.note"),
      inputType: "text",
    },
  ];

  const columnDocRows = [
    { key: "member_number", req: true },
    { key: "amount", req: true },
    { key: "value_one", req: true },
    { key: "is_increase", req: false },
    { key: "note", req: false },
  ];

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={t("onboarding.coop_title")}
      footer={null}
      width={720}
      destroyOnHidden
    >
      <Space direction="vertical" size="middle" className="w-full">
        <Paragraph type="secondary">{t("onboarding.coop_intro")}</Paragraph>

        <Alert
          type="info"
          showIcon
          message={t("onboarding.coop_unconfirmed_notice")}
        />

        <Card size="small" title={t("onboarding.columns_title")}>
          <Table
            size="small"
            pagination={false}
            rowKey="key"
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
                render: (r: boolean) => (r ? t("common.yes") : t("common.no")),
              },
              {
                title: t("onboarding.col_meaning"),
                dataIndex: "key",
                key: "meaning",
                render: (k: string) => t(`onboarding.coop_help.${k}`),
              },
            ]}
          />
          <div style={{ marginTop: 12 }}>
            {uploadAllowed ? (
              <DownloadCsvTemplateButton
                columns={columns}
                filename="coop_shares_template.csv"
                modelName="coop_share"
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
    </Modal>
  );
}
