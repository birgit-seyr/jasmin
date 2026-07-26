import { Alert, Card, Modal, Space, Table, Typography } from "antd";
import { useTranslation } from "react-i18next";
import DownloadCsvTemplateButton from "@shared/ui/DownloadCsvTemplateButton";

const { Paragraph, Text } = Typography;

interface SepaMandateImportModalProps {
  open: boolean;
  onClose: () => void;
  /** Tenant ``allow_upload_for_data_lists`` — gates the CSV upload/validate. */
  uploadAllowed: boolean;
  /** Refetch the mandates page after a successful (partial or full) import. */
  onUploadSuccess?: () => void;
}

/**
 * Onboarding modal for bulk-importing EXISTING SEPA direct-debit mandates.
 *
 * A mandate is the SEPA fields on a member's billing profile (one per member),
 * so each row CREATES that member's profile, keyed by member number. Create-only:
 * a member who already has a billing profile is reported as a per-row conflict
 * and left untouched, so a live mandate is never overwritten. Opened from the
 * bottom of the SEPA mandates page.
 */
export default function SepaMandateImportModal({
  open,
  onClose,
  uploadAllowed,
  onUploadSuccess,
}: SepaMandateImportModalProps) {
  const { t } = useTranslation();

  // Natural keys + mandate fields — never DB ids. Drives the 3-row template
  // download and the upload's ``model_name``.
  const columns = [
    {
      dataIndex: "member_number",
      title: t("onboarding.sepa_col.member_number"),
      inputType: "integer",
    },
    {
      dataIndex: "account_holder",
      title: t("onboarding.sepa_col.account_holder"),
      inputType: "text",
    },
    {
      dataIndex: "iban",
      title: t("onboarding.sepa_col.iban"),
      inputType: "text",
    },
    {
      dataIndex: "sepa_mandate_reference",
      title: t("onboarding.sepa_col.reference"),
      inputType: "text",
    },
    {
      dataIndex: "sepa_mandate_signed_at",
      title: t("onboarding.sepa_col.signed_at"),
      inputType: "date",
    },
    {
      dataIndex: "sepa_mandate_paper_received_at",
      title: t("onboarding.sepa_col.paper_received_at"),
      inputType: "date",
    },
  ];

  const columnDocRows = [
    { key: "member_number", req: true },
    { key: "account_holder", req: true },
    { key: "iban", req: true },
    { key: "reference", req: false },
    { key: "signed_at", req: true },
    { key: "paper_received_at", req: false },
  ];

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={t("onboarding.sepa_title")}
      footer={null}
      width={720}
      destroyOnHidden
    >
      <Space direction="vertical" size="middle" className="w-full">
        <Paragraph type="secondary">{t("onboarding.sepa_intro")}</Paragraph>

        <Alert
          type="info"
          showIcon
          message={t("onboarding.sepa_create_only_notice")}
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
                render: (k: string) => t(`onboarding.sepa_help.${k}`),
              },
            ]}
          />
          <div style={{ marginTop: 12 }}>
            {uploadAllowed ? (
              <DownloadCsvTemplateButton
                columns={columns}
                filename="sepa_mandates_template.csv"
                modelName="sepa_mandate"
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
