import { DownloadOutlined, UploadOutlined } from "@ant-design/icons";
import { Button, Modal, Upload, message } from "antd";
import { isValidElement, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import axiosService from "@shared/services/api";
import { getErrorMessage } from "@shared/utils/apiError";
import { downloadBlob } from "@shared/utils";
import type { DataImportResponse } from "@shared/api/generated/models";
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
}

// Maps an EditableColumnConfig `inputType` to a short, comma-free type hint
// suitable for a CSV row. The hint row is meant to be visible (Excel renders
// it as row 2) and skipped on upload (`skiprows=1` in pandas, `header=1` etc).
const TYPE_HINTS: Record<string, string> = {
  text: "string",
  optional: "string",
  select: "string",
  checkbox: "true|false",
  switch: "true|false",
  date: "YYYY-MM-DD",
  datepicker: "YYYY-MM-DD",
  time: "HH:MM",
  number: "number",
  integer: "integer",
  positive_integer: "integer (>=0)",
  negative_integer: "integer (<=0)",
  decimal1: "decimal (1dp)",
  decimal2: "decimal (2dp)",
  decimal3: "decimal (3dp)",
  positive_decimal2: "decimal (>=0 2dp)",
  negative_decimal2: "decimal (<=0 2dp)",
  positive_decimal3: "decimal (>=0 3dp)",
  negative_decimal3: "decimal (<=0 3dp)",
  percentage: "percentage",
  kw: "week number",
};

function typeHintFor(col: ColumnLike): string {
  const inputType = col.inputType;
  // For select inputs with an explicit static option list, surface the
  // actual values so the user can copy them verbatim into the cell.
  // Per-row option functions and async-loaded options fall back to
  // "string" (we have no record to evaluate against at download time).
  if (
    inputType === "select" &&
    Array.isArray(col.options) &&
    col.options.length > 0
  ) {
    return col.options.map((opt) => String(opt.value)).join("|");
  }
  if (!inputType) return "string";
  return TYPE_HINTS[inputType] ?? "string";
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
}: DownloadCsvTemplateButtonProps) {
  const { t } = useTranslation();

  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<DataImportResponse | null>(null);
  const [resultOpen, setResultOpen] = useState(false);

  const handleUpload = async (file: File): Promise<boolean> => {
    if (!modelName) return false;
    setUploading(true);
    try {
      const form = new FormData();
      form.append("model_name", modelName);
      form.append("file", file);
      const response = await axiosService.post<DataImportResponse>(
        "/api/commissioning/data_import/",
        form,
        { headers: { "Content-Type": "multipart/form-data" } },
      );
      setResult(response.data);
      setResultOpen(true);
      if (response.data.successful > 0 && onUploadSuccess) {
        onUploadSuccess();
      }
    } catch (err) {
      message.error(
        getErrorMessage(err, t("csv_upload.failed")),
      );
    } finally {
      setUploading(false);
    }
    // Always return false so antd's Upload doesn't keep the file in its
    // internal list — we manage the lifecycle ourselves.
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
        // A function `disabled` means per-row — keep it (the new-row case is
        // editable). Only literal `true` means "always read-only".
        col.disabled !== true,
    );

    const derivedHeaders =
      headers ?? usableColumns.map((col) => String(col.dataIndex));
    if (derivedHeaders.length === 0) return;

    // Three rows:
    //   row 0: translated, human-readable titles (for the user reading in Excel)
    //   row 1: machine-readable dataIndex names (the actual upload schema)
    //   row 2: short, comma-free type hint per column
    // When `headers` is given explicitly we don't have access to column titles
    // or inputType — both fall back to the dataIndex / "string".
    const titleRow = headers
      ? derivedHeaders
      : usableColumns.map(
          (col, i) => extractText(col.title) || derivedHeaders[i],
        );
    const typeRow = headers
      ? derivedHeaders.map(() => "string")
      : usableColumns.map((col) => typeHintFor(col));

    const csv =
      [titleRow, derivedHeaders, typeRow]
        .map((row) => row.map(csvCell).join(","))
        .join("\n") + "\n";
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    downloadBlob(blob, filename.endsWith(".csv") ? filename : `${filename}.csv`);
  };

  return (
    <>
      <Button
        className="csv-template-button"
        size="small"
        icon={<DownloadOutlined />}
        onClick={handleClick}
        style={{
          padding: 2,
          height: "auto",
          fontSize: "0.85em",
          marginTop: "0.4em",
        }}
      >
        {label ?? t("download.csv_template")}
      </Button>
      <ToolTipIcon title={t("tooltip.explainer_csv_template")} />

      <span style={{ marginLeft: "0.5em" }}>
        <Upload
          accept=".csv,text/csv"
          showUploadList={false}
          beforeUpload={(file) => {
            handleUpload(file as unknown as File);
            return false;
          }}
          disabled={uploading}
        >
          <Button
            className="csv-template-button"
            size="small"
            icon={<UploadOutlined />}
            loading={uploading}
            style={{
              padding: 2,
              height: "auto",
              fontSize: "0.85em",
              marginTop: "0.4em",
            }}
          >
            {t("csv_upload.button")}
          </Button>
        </Upload>
        <ToolTipIcon
          title={t("tooltip.explainer_csv_upload")}
        />
      </span>

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
              <strong>{result.model_name}</strong> —{" "}
              {t("csv_upload.summary", {
                total: result.total_rows,
                successful: result.successful,
                failed: result.failed,
                defaultValue:
                  "{{total}} rows • {{successful}} imported • {{failed}} failed",
              })}
            </p>
            {result.errors.length > 0 && (
              <>
                <p style={{ marginTop: "1em", fontWeight: 500 }}>
                  {t("csv_upload.errors_heading")}
                </p>
                <div style={{ maxHeight: 320, overflow: "auto" }}>
                  <table style={{ width: "100%", fontSize: "0.85em" }}>
                    <thead>
                      <tr>
                        <th style={{ textAlign: "left", paddingRight: "1em" }}>
                          {t("csv_upload.col_row")}
                        </th>
                        <th style={{ textAlign: "left" }}>
                          {t("csv_upload.col_error")}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.errors.map((err) => (
                        <tr key={err.row}>
                          <td
                            style={{
                              verticalAlign: "top",
                              paddingRight: "1em",
                            }}
                          >
                            {err.row}
                          </td>
                          <td style={{ verticalAlign: "top" }}>{err.error}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        )}
      </Modal>
    </>
  );
}
