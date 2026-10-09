import { DownloadOutlined, UploadOutlined } from "@ant-design/icons";
import { Alert, Button, Modal, Upload } from "antd";
import type { RcFile } from "antd/es/upload";
import { isValidElement, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import axiosService from "@shared/services/api";
import { getErrorMessage, messageForErrorCode } from "@shared/utils/apiError";
import { downloadBlob, notify } from "@shared/utils";
import type {
  DataImportErrorItem,
  DataImportResponse,
} from "@shared/api/generated/models";
import ReadOnlyReportTable from "@shared/tables/ReadOnlyReportTable";
import ToolTipIcon from "./ToolTipIcon";

/**
 * Tiny shape we accept — kept loose so the button works with the various
 * column types around the app (EditableColumnConfig and friends) without
 * forcing a generic / import cycle. The `disabled` function arg is typed
 * as `any` because TS treats function parameters contravariantly: a
 * stricter `unknown` here would reject callers whose function takes a
 * tighter record shape (TableRecord etc.).
 */
interface ColumnLike {
  dataIndex?: string | number;
  title?: ReactNode;
  hidden?: boolean;
  hideInModal?: boolean;
  disabled?: boolean | ((record: any) => boolean);
  // Read-only grid columns are display-only (masked aliases like
  // ``iban_masked``) or server-managed, so by default they must NOT become
  // import-template columns. Excluded from the template below unless the
  // column opts back in via ``importable``.
  readOnly?: boolean;
  /**
   * Opts a `readOnly` / always-`disabled` column back INTO the template.
   * Some columns are locked in the grid only because editing a LIVE row
   * would falsify history, yet are legitimate inputs when ONBOARDING
   * existing records (``member_number`` carried over from the tenant's
   * previous system, ``entry_date`` for a historical admission date). The
   * backend's import serializer must accept the field for this to be
   * correct — the flag only changes what the template offers.
   */
  importable?: boolean;
  /** Whether the field is mandatory. Not used for the template itself (a
   * template is empty by definition) — read by `CsvImportModal` to mark the
   * column as required in its reference table. */
  required?: boolean;
  inputType?: string;
  /** Select-input options. When present as a static array on a column
   * with ``inputType: "select"``, the template's type-hint row lists the
   * available values (e.g. ``KG|PCS|BUNCH``). Per-row option functions
   * (record → options) are kept in the type to stay compatible with
   * EditableColumnConfig, but fall back to "string" in the template. */
  options?:
    | Array<{ value: string | number; label?: unknown }>
    | ((record: any) => Array<{ value: string | number; label?: unknown }>);
}

interface DownloadCsvTemplateButtonProps {
  /** Source columns to derive header names from — same array the table uses. */
  columns: ColumnLike[];
  /** File saved on disk (no path, with `.csv`). */
  filename: string;
  /** Optional explicit overrides — if provided, replaces the derived headers. */
  headers?: string[];
  /** Button label; defaults to the `csv_template.download` i18n key. */
  label?: string;
  /**
   * Registry key matching the backend ``MODEL_IMPORT_REGISTRY`` (e.g.
   * ``"share_article"``, ``"crate"``). When set AND the tenant has
   * ``allow_upload_for_data_lists`` enabled, an Upload button is rendered
   * next to the download button. Without this prop the upload affordance is
   * hidden — pages that don't have a registered serializer simply leave it
   * unset.
   */
  modelName?: string;
  /** Refetch / state-refresh hook called after a successful import. */
  onUploadSuccess?: () => void;
  /**
   * Called after a FULLY successful real import (every row imported, none
   * failed). The onboarding modals wire this to close themselves so the office
   * returns to the freshly-refetched page. NOT called for dry runs or partial
   * imports — those keep the result modal open so any failures stay visible.
   */
  onImported?: () => void;
  /**
   * When true, also render a "validate (dry run)" upload that posts
   * ``dry_run=true`` — the backend resolves every row (incl. FK natural keys)
   * and reports what WOULD import without persisting anything. Meant for
   * many-FK imports like subscriptions where the office wants to fix the whole
   * CSV before committing. Off by default (existing pages unaffected).
   */
  allowDryRun?: boolean;
  /**
   * Field values the backend sets on every imported row, over the file's own
   * cells — for a page whose rows all share values its template leaves out.
   */
  fixedValues?: Record<string, unknown>;
}

// A failed row in the office's language when its code has a translation,
// otherwise in the server's words.
function rowErrorMessage(rowError: DataImportErrorItem): string {
  const translated = rowError.code
    ? messageForErrorCode(rowError.code, rowError.details)
    : undefined;
  return translated ?? rowError.error;
}

// Maps an EditableColumnConfig `inputType` to the i18n key of a short,
// comma-free type hint for the template's third row. The importer skips that
// row by position, so the hint is written in the office's language.
const TYPE_HINT_KEYS: Record<string, string> = {
  text: "csv_upload.type_hint.text",
  optional: "csv_upload.type_hint.text",
  select: "csv_upload.type_hint.text",
  checkbox: "csv_upload.type_hint.true_false",
  switch: "csv_upload.type_hint.true_false",
  date: "csv_upload.type_hint.date",
  datepicker: "csv_upload.type_hint.date",
  time: "csv_upload.type_hint.time",
  number: "csv_upload.type_hint.number",
  integer: "csv_upload.type_hint.integer",
  positive_integer: "csv_upload.type_hint.integer_non_negative",
  negative_integer: "csv_upload.type_hint.integer_non_positive",
  decimal1: "csv_upload.type_hint.decimal_1dp",
  decimal2: "csv_upload.type_hint.decimal_2dp",
  decimal3: "csv_upload.type_hint.decimal_3dp",
  positive_decimal2: "csv_upload.type_hint.decimal_non_negative_2dp",
  negative_decimal2: "csv_upload.type_hint.decimal_non_positive_2dp",
  positive_decimal3: "csv_upload.type_hint.decimal_non_negative_3dp",
  negative_decimal3: "csv_upload.type_hint.decimal_non_positive_3dp",
  percentage: "csv_upload.type_hint.percentage",
  kw: "csv_upload.type_hint.week_number",
};

function typeHintKeyFor(col: ColumnLike): string {
  return (
    (col.inputType && TYPE_HINT_KEYS[col.inputType]) ||
    "csv_upload.type_hint.text"
  );
}

function selectValuesHint(col: ColumnLike): string | undefined {
  // A select with a static option list lists its values, so the user can
  // copy them verbatim into the cell. Per-row option functions have no record
  // to evaluate against at download time and fall back to the text hint.
  if (
    col.inputType === "select" &&
    Array.isArray(col.options) &&
    col.options.length > 0
  ) {
    return col.options.map((opt) => String(opt.value)).join("|");
  }
  return undefined;
}

// Best-effort extraction of plain text from a ReactNode. Handles strings,
// numbers, fragments, arrays, and elements that wrap their text in children
// (Tooltip/Fragment/span wrapping a translated string). Returns "" for
// anything we can't walk into (icons, functions, etc.).
function extractText(node: ReactNode): string {
  if (node === null || node === undefined || node === false || node === true) {
    return "";
  }
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (isValidElement(node)) {
    const props = node.props as { children?: ReactNode };
    return extractText(props.children);
  }
  return "";
}

// RFC 4180-style CSV cell escape: wrap in quotes if it contains a comma,
// quote, or newline; double up internal quotes.
function csvCell(value: string): string {
  if (/[",\n\r]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

/**
 * "Download empty CSV template" affordance.
 *
 * Generates a single-line CSV (just the header row, no data) from the table
 * columns the page already defines. Computed / hidden / always-disabled
 * columns are filtered out so the file only contains fields the user would
 * actually fill in when uploading. The placement is meant to be a quiet
 * link-style button under the page's ExplainerText.
 */
export default function DownloadCsvTemplateButton({
  columns,
  filename,
  headers,
  label,
  modelName,
  onUploadSuccess,
  onImported,
  allowDryRun = false,
  fixedValues,
}: DownloadCsvTemplateButtonProps) {
  const { t } = useTranslation();

  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<DataImportResponse | null>(null);
  const [resultOpen, setResultOpen] = useState(false);
  const [wasDryRun, setWasDryRun] = useState(false);

  const handleUpload = async (file: RcFile, dryRun: boolean): Promise<void> => {
    if (!modelName) return;
    setUploading(true);
    try {
      const form = new FormData();
      form.append("model_name", modelName);
      form.append("file", file);
      if (dryRun) form.append("dry_run", "true");
      if (fixedValues) form.append("fixed_values", JSON.stringify(fixedValues));
      const response = await axiosService.post<DataImportResponse>(
        "/api/commissioning/data_import/",
        form,
        { headers: { "Content-Type": "multipart/form-data" } },
      );
      setResult(response.data);
      setWasDryRun(dryRun);
      const { successful, failed } = response.data;
      // A dry run persists nothing, so never trigger a data refetch for it.
      if (!dryRun && successful > 0) {
        onUploadSuccess?.();
      }
      // A fully successful real import needs no summary to act on: confirm with
      // a toast and let the parent close so the office lands back on the
      // freshly-refetched page. Dry runs and partial imports (some rows failed)
      // still open the result modal so the outcome / failures stay visible.
      if (!dryRun && successful > 0 && failed === 0) {
        notify.success(t("csv_upload.import_success", { count: successful }));
        onImported?.();
      } else {
        setResultOpen(true);
      }
    } catch (err) {
      notify.error(getErrorMessage(err, t("csv_upload.failed")));
    } finally {
      setUploading(false);
    }
  };

  // handleUpload reports its own failures, so nothing is left to await here.
  // Returning false stops antd's Upload from posting the file itself.
  const startUpload = (file: RcFile, dryRun = false): false => {
    void handleUpload(file, dryRun);
    return false;
  };

  const handleClick = () => {
    // Pick the columns the user is meant to fill (header overrides bypass the
    // filter entirely — caller knows best).
    const usableColumns = columns.filter(
      (col) =>
        typeof col.dataIndex === "string" &&
        col.hidden !== true &&
        col.hideInModal !== true &&
        // `importable` overrides the two lock flags below: the column is
        // locked in the grid but IS a valid input when onboarding existing
        // records (see the prop's doc comment).
        (col.importable === true ||
          // Read-only display columns (masked aliases / server-managed
          // fields) are not importable serializer inputs — keep them out of
          // the template.
          (col.readOnly !== true &&
            // A function `disabled` means per-row — keep it (the new-row case
            // is editable). Only literal `true` means "always read-only".
            col.disabled !== true)),
    );

    const derivedHeaders =
      headers ?? usableColumns.map((col) => String(col.dataIndex));
    if (derivedHeaders.length === 0) return;

    // Three rows:
    //   row 0: translated, human-readable titles (for the user reading in Excel)
    //   row 1: machine-readable dataIndex names (the actual upload schema)
    //   row 2: short, comma-free type hint per column
    // When `headers` is given explicitly we don't have access to column titles
    // or inputType — both fall back to the dataIndex / the text hint.
    const titleRow = headers
      ? derivedHeaders
      : usableColumns.map(
          (col, i) => extractText(col.title) || derivedHeaders[i],
        );
    const typeRow = headers
      ? derivedHeaders.map(() => t("csv_upload.type_hint.text"))
      : usableColumns.map(
          (col) => selectValuesHint(col) ?? t(typeHintKeyFor(col)),
        );

    const csv =
      [titleRow, derivedHeaders, typeRow]
        .map((row) => row.map(csvCell).join(","))
        .join("\n") + "\n";
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    downloadBlob(
      blob,
      filename.endsWith(".csv") ? filename : `${filename}.csv`,
    );
  };

  return (
    <>
      <div className="mb-1em">
        <Button
          className="csv-template-button"
          icon={<DownloadOutlined />}
          onClick={handleClick}
        >
          {label ?? t("download.csv_template")}
        </Button>
        <ToolTipIcon title={t("tooltip.explainer_csv_template")} />
      </div>
      {allowDryRun && modelName && (
        <div className="mb-1em">
          <Upload
            accept=".csv,text/csv"
            showUploadList={false}
            beforeUpload={(file) => startUpload(file, true)}
            disabled={uploading}
          >
            <Button
              className="csv-template-button"
              icon={<UploadOutlined />}
              loading={uploading}
            >
              {t("csv_upload.validate")}
            </Button>
          </Upload>
          <ToolTipIcon title={t("tooltip.explainer_csv_validate")} />
        </div>
      )}
      <div>
        <Upload
          accept=".csv,text/csv"
          showUploadList={false}
          beforeUpload={(file) => startUpload(file)}
          disabled={uploading}
        >
          <Button
            className="csv-template-button"
            icon={<UploadOutlined />}
            loading={uploading}
          >
            {t("csv_upload.button")}
          </Button>
        </Upload>
        <ToolTipIcon title={t("tooltip.explainer_csv_upload")} />
      </div>

      <Modal
        open={resultOpen}
        title={t("csv_upload.result_title")}
        onCancel={() => setResultOpen(false)}
        onOk={() => setResultOpen(false)}
        width={720}
      >
        {result && (
          <div>
            <p>
              <strong>{t(`csv_upload.model.${result.model_name}`)}</strong> —{" "}
              {t("csv_upload.summary", {
                total: result.total_rows,
                successful: result.successful,
                failed: result.failed,
              })}
            </p>
            {wasDryRun && (
              <p className="csv-import-result__dry-run">
                {t("csv_upload.dry_run_notice")}
              </p>
            )}
            {result.total_rows === 0 ? (
              <Alert
                type="warning"
                showIcon
                className="mt-1em"
                message={t("csv_upload.no_rows")}
              />
            ) : result.errors.length === 0 ? (
              <Alert
                type="success"
                showIcon
                className="mt-1em"
                message={t("csv_upload.all_ok")}
              />
            ) : (
              <>
                <p className="csv-import-result__errors-heading">
                  {t("csv_upload.errors_heading")}
                </p>
                <ReadOnlyReportTable<DataImportErrorItem>
                  rowKey="row"
                  pagination={false}
                  scroll={{ y: 320 }}
                  dataSource={result.errors}
                  columns={[
                    {
                      title: t("csv_upload.col_row"),
                      dataIndex: "row",
                      width: 80,
                    },
                    {
                      title: t("csv_upload.col_error"),
                      key: "error",
                      render: (_, rowError) => rowErrorMessage(rowError),
                    },
                  ]}
                />
              </>
            )}
          </div>
        )}
      </Modal>
    </>
  );
}
