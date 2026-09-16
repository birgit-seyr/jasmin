import { Alert, Modal, Space, Typography } from "antd";
import type { ComponentProps } from "react";
import { useTranslation } from "react-i18next";
import DownloadCsvTemplateButton from "@shared/ui/DownloadCsvTemplateButton";

const { Paragraph, Text } = Typography;

interface MembersImportModalProps {
  open: boolean;
  onClose: () => void;
  /** The member grid columns — drive the CSV template (same as the page). */
  columns: ComponentProps<typeof DownloadCsvTemplateButton>["columns"];
  filename: string;
  /** Whether the tenant allows data-list uploads (gates the CSV upload). */
  uploadAllowed: boolean;
  onUploadSuccess: () => void;
}

/**
 * Onboarding modal for importing a tenant's EXISTING members via CSV: download
 * the template, validate (dry run), then import. Manual entry happens in the
 * grid while the tenant's onboarding mode is on (switch at the bottom of the
 * Members page), which the modal points to.
 *
 * Opened from the bottom of the Members page.
 */
export default function MembersImportModal({
  open,
  onClose,
  columns,
  filename,
  uploadAllowed,
  onUploadSuccess,
}: MembersImportModalProps) {
  const { t } = useTranslation();

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={t("onboarding.members_title")}
      footer={null}
      width={620}
      destroyOnHidden
    >
      <Space direction="vertical" size="middle" className="w-full">
        <Paragraph type="secondary">{t("onboarding.members_intro")}</Paragraph>

        <div>
          <Text strong>{t("onboarding.members_csv_title")}</Text>
          {uploadAllowed ? (
            <div className="onboarding-import-section__body">
              <DownloadCsvTemplateButton
                columns={columns}
                filename={filename}
                modelName="member"
                onUploadSuccess={onUploadSuccess}
                onImported={onClose}
                allowDryRun
              />
            </div>
          ) : (
            <Paragraph
              type="secondary"
              className="onboarding-import-section__body"
            >
              {t("onboarding.members_upload_disabled")}
            </Paragraph>
          )}
        </div>

        <Alert type="info" showIcon message={t("onboarding.members_manual_hint")} />
      </Space>
    </Modal>
  );
}
