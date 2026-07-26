import { Alert, Button, Modal, Space, Typography } from "antd";
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
  /** The members-grid "manual transfer" mode (makes entry_date editable). */
  manualTransferActive: boolean;
  onToggleManualTransfer: () => void;
}

/**
 * Onboarding modal for importing a tenant's EXISTING members. Two ways in:
 *   1. CSV — download the template, validate (dry run), then import.
 *   2. Manual entry — turn on "manual transfer", which unlocks the normally
 *      server-stamped ``entry_date`` (GenG §30 Eintrittsdatum) in the grid so
 *      the office can backdate each member's historical admission date.
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
  manualTransferActive,
  onToggleManualTransfer,
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

        {/* 1) CSV */}
        <div>
          <Text strong>{t("onboarding.members_csv_title")}</Text>
          {uploadAllowed ? (
            <div style={{ marginTop: 8 }}>
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
            <Paragraph type="secondary" style={{ marginTop: 8 }}>
              {t("onboarding.members_upload_disabled")}
            </Paragraph>
          )}
        </div>

        {/* 2) Manual entry (unlocks entry_date) */}
        <div>
          <Text strong>{t("onboarding.members_manual_title")}</Text>
          <Alert
            type="info"
            showIcon
            style={{ marginTop: 8 }}
            message={t("onboarding.members_manual_explain")}
          />
          <Button
            type={manualTransferActive ? "primary" : "default"}
            danger={manualTransferActive}
            onClick={onToggleManualTransfer}
            aria-pressed={manualTransferActive}
            style={{ marginTop: 8 }}
          >
            {manualTransferActive ? "● " : ""}
            {t("members.manual_transfer_toggle")}
          </Button>
        </div>
      </Space>
    </Modal>
  );
}
