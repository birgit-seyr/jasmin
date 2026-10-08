import { Alert, Button, Card, Modal, Space, Typography } from "antd";
import { useState, type ComponentProps, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useRoles } from "@shared/auth";
import CsvColumnsTable from "@shared/ui/CsvColumnsTable";
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
   * below is derived from this one array on purpose: a hand-written doc list
   * drifts from it and documents column names the importer rejects.
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
  /** Field values the backend sets on every row, over the file's own cells. */
  fixedValues?: Record<string, unknown>;
}

/**
 * Generic "import this list from CSV" modal: template download → validate
 * (dry run) → upload, plus an optional per-column reference table.
 *
 * Lives in `shared/` because several unrelated features use it.
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
  fixedValues,
}: CsvImportModalProps) {
  const { t } = useTranslation();
  const entity = entityLabel ?? t(`csv_upload.model.${modelName}`);

  // Only the columns the template will actually emit — mirrors the filter in
  // DownloadCsvTemplateButton so the docs can't advertise a column the file
  // won't contain.
  const documented = columns.filter(
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
            <CsvColumnsTable
              rows={documented.map((col) => ({
                field: String(col.dataIndex),
                required: col.required === true,
                meaning: help?.[String(col.dataIndex)] ?? "",
              }))}
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
              fixedValues={fixedValues}
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
   * Tenant `allow_upload_for_data_lists`. False renders nothing at all.
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
 * Offered to the office only, as the import endpoint takes no other role.
 */
export function CsvImportButton({
  uploadAllowed,
  label,
  className,
  ...modalProps
}: CsvImportButtonProps) {
  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const [open, setOpen] = useState(false);

  if (!uploadAllowed || !isOffice) return null;

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
