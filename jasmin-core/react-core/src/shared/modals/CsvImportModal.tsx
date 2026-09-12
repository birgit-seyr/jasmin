import { Alert, Button, Card, Modal, Space, Table, Typography } from "antd";
import { useState, type ComponentProps, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import DownloadCsvTemplateButton from "@shared/ui/DownloadCsvTemplateButton";

const { Paragraph, Text } = Typography;

type TemplateColumns = ComponentProps<
  typeof DownloadCsvTemplateButton
>["columns"];

export interface CsvImportModalProps {
  open: boolean;
  onClose: () => void;
  /**
   * The SAME column array the page's table uses — it generates the downloadable
   * template, so its `dataIndex` values ARE the wire schema. The docs table
   * below is derived from this one array on purpose: the older hand-written
   * `columnDocRows` lists drifted from it and documented column names the
   * importer rejects.
   */
  columns: TemplateColumns;
  filename: string;
  /** Registry key from the backend `MODEL_IMPORT_REGISTRY`. */
  modelName: string;
  onUploadSuccess?: () => void;
  /** Overrides the title's entity label (defaults to `csv_upload.model.<modelName>`). */
  entityLabel?: string;
  /** Extra explanation under the intro — e.g. a create-only caveat. */
  notice?: ReactNode;
  /** Per-field help, keyed by `dataIndex`. Omit to hide the columns table. */
  help?: Record<string, string>;
}

/**
 * Generic "import this list from CSV" modal: template download → validate
 * (dry run) → upload, plus an optional per-column reference table.
 *
 * Extracted from the onboarding modals (members / coop shares / SEPA mandates /
 * subscriptions) so the plain list pages get the same affordance instead of two
 * bare buttons with no dry run. Lives in `shared/` because several unrelated
 * features use it.
 */
export function CsvImportModal({
  open,
  onClose,
  columns,
  filename,
  modelName,
  onUploadSuccess,
  entityLabel,
  notice,
  help,
}: CsvImportModalProps) {
  const { t } = useTranslation();
  const entity = entityLabel ?? t(`csv_upload.model.${modelName}`);

  // Only the columns the template will actually emit — mirrors the filter in
  // DownloadCsvTemplateButton so the docs can't advertise a column the file
  // won't contain.
  const documented = (columns ?? []).filter(
    (col) =>
      typeof col.dataIndex === "string" &&
      col.hidden !== true &&
      col.hideInModal !== true &&
      (col.importable === true ||
        (col.readOnly !== true && col.disabled !== true)),
  );

  const showHelpTable = Boolean(help) && documented.length > 0;

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={t("csv_upload.import_title", { entity })}
      footer={null}
      width={720}
      destroyOnHidden
    >
      <Space direction="vertical" size="middle" className="w-full">
        <Paragraph type="secondary">{t("csv_upload.intro")}</Paragraph>

        {notice ? <Alert type="info" showIcon message={notice} /> : null}

        <Card size="small" title={t("csv_upload.columns_title")}>
          {showHelpTable ? (
            <Table
              size="small"
              pagination={false}
              rowKey="field"
              dataSource={documented.map((col) => ({
                field: String(col.dataIndex),
                required: col.required === true,
                meaning: help?.[String(col.dataIndex)] ?? "",
              }))}
              columns={[
                {
                  title: t("csv_upload.col_field"),
                  dataIndex: "field",
                  render: (field: string) => <code>{field}</code>,
                },
                {
                  title: t("csv_upload.col_required"),
                  dataIndex: "required",
                  render: (required: boolean) =>
                    required ? t("common.yes") : t("common.no"),
                },
                {
                  title: t("csv_upload.col_meaning"),
                  dataIndex: "meaning",
                },
              ]}
            />
          ) : (
            <Text type="secondary">
              {t("csv_upload.columns_from_template")}
            </Text>
          )}

          <div style={{ marginTop: 12 }}>
            <DownloadCsvTemplateButton
              columns={columns}
              filename={filename}
              modelName={modelName}
              allowDryRun
              onUploadSuccess={onUploadSuccess}
              onImported={onClose}
            />
          </div>
        </Card>
      </Space>
    </Modal>
  );
}

export interface CsvImportButtonProps extends Omit<
  CsvImportModalProps,
  "open" | "onClose"
> {
  /**
   * Tenant `allow_upload_for_data_lists`. False renders nothing at all —
   * matching what the bare template buttons did on the list pages.
   */
  uploadAllowed: boolean;
  /** Button label; defaults to `csv_upload.open`. */
  label?: string;
  /** Appended to the button's own class — for a page needing different spacing. */
  className?: string;
}

/**
 * The list-page trigger: one quiet button that opens {@link CsvImportModal}.
 * Drop-in replacement for a bare `DownloadCsvTemplateButton` on a list page.
 */
export function CsvImportButton({
  uploadAllowed,
  label,
  className,
  ...modalProps
}: CsvImportButtonProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  if (!uploadAllowed) return null;

  return (
    <>
      <Button
        size="small"
        className={
          className ? `csv-import-button ${className}` : "csv-import-button"
        }
        onClick={() => setOpen(true)}
      >
        {label ?? t("csv_upload.open")}
      </Button>
      <CsvImportModal
        {...modalProps}
        open={open}
        onClose={() => setOpen(false)}
      />
    </>
  );
}

export default CsvImportModal;
