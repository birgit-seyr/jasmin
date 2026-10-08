import { useState, useMemo, useCallback, isValidElement } from "react";
import type { ReactNode } from "react";
import { Modal, Button } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import {
  buildCsvString,
  csvDecimal,
  downloadCsvBlob,
  resolveCsvDialect,
} from "@shared/utils";
import { CheckboxMultiSelectList } from "@shared/ui";
import { useTenant } from "@hooks/index";

interface ColumnDef {
  title?: ReactNode;
  dataIndex?: string;
  key?: string;
  children?: ColumnDef[];
  [key: string]: unknown;
}

interface CsvExportModalProps {
  open: boolean;
  onClose: () => void;
  columns: ColumnDef[];
  data: Record<string, unknown>[];
  filename?: string;
}

// The grid's input types whose values are decimals. The API sends a decimal as
// a string, so only the column's type tells it apart from text.
const DECIMAL_INPUT_TYPES = new Set([
  "number",
  "decimal1",
  "decimal2",
  "decimal3",
  "positive_decimal2",
  "positive_decimal3",
  "negative_decimal2",
  "negative_decimal3",
  "percentage",
]);

function getColumnTitle(title: ReactNode): string {
  if (typeof title === "string") return title;
  if (typeof title === "number") return String(title);
  if (isValidElement(title)) {
    const children = (title.props as Record<string, unknown>).children;
    if (typeof children === "string") return children;
    if (Array.isArray(children)) {
      return children
        .map((child) => getColumnTitle(child as ReactNode))
        .join("");
    }
    if (children) return getColumnTitle(children as ReactNode);
  }
  return "";
}

export default function ExportCsv({
  open,
  onClose,
  columns,
  data,
  filename = "export",
}: CsvExportModalProps) {
  const { t } = useTranslation();
  const { getSetting } = useTenant();
  const dialect = useMemo(
    () => resolveCsvDialect(getSetting("csv_format", "de") as string),
    [getSetting],
  );

  // A column drawn through `render` may be a button or a link (a price
  // button, an orders link) that carries a `dataIndex` only as the table's
  // key: no row has a field under it, so it has nothing to export. A data
  // column the grid merely formats keeps its field in the rows, even when the
  // field is empty.
  const exportableColumns = useMemo(() => {
    const flatCols: ColumnDef[] = [];
    const flatten = (cols: ColumnDef[]) => {
      for (const col of cols) {
        if (col.children) {
          flatten(col.children);
        } else if (col.dataIndex) {
          flatCols.push(col);
        }
      }
    };
    flatten(columns);
    return flatCols.filter(
      (col) =>
        !col.render ||
        data.some((row) => (col.dataIndex as string) in row),
    );
  }, [columns, data]);

  // The office's unticked columns, so a column that becomes exportable once
  // the rows arrive starts out ticked.
  const [deselectedKeys, setDeselectedKeys] = useState<string[]>([]);
  const exportableKeys = useMemo(
    () => exportableColumns.map((col) => col.dataIndex as string),
    [exportableColumns],
  );
  const selectedKeys = useMemo(
    () => exportableKeys.filter((key) => !deselectedKeys.includes(key)),
    [exportableKeys, deselectedKeys],
  );
  const handleSelectionChange = useCallback(
    (keys: string[]) =>
      setDeselectedKeys(exportableKeys.filter((key) => !keys.includes(key))),
    [exportableKeys],
  );

  const noneSelected = selectedKeys.length === 0;

  const items = useMemo(
    () =>
      exportableColumns.map((col) => ({
        key: col.dataIndex as string,
        label: getColumnTitle(col.title),
      })),
    [exportableColumns],
  );

  const handleExport = useCallback(() => {
    const selectedCols = exportableColumns.filter((col) =>
      selectedKeys.includes(col.dataIndex as string),
    );

    const headers = selectedCols.map((col) => getColumnTitle(col.title));
    const rows = data.map((row) =>
      selectedCols.map((col) => {
        const value = row[col.dataIndex as string];
        return DECIMAL_INPUT_TYPES.has(col.inputType as string)
          ? csvDecimal(value)
          : value;
      }),
    );
    downloadCsvBlob(buildCsvString(headers, rows, dialect), filename);
    onClose();
  }, [data, exportableColumns, selectedKeys, filename, onClose, dialect]);

  return (
    <Modal
      title={t("common.export_csv")}
      open={open}
      onCancel={onClose}
      width={400}
      footer={[
        <Button key="cancel" onClick={onClose}>
          {t("common.cancel")}
        </Button>,
        <Button
          key="export"
          type="primary"
          icon={<DownloadOutlined />}
          disabled={noneSelected}
          onClick={handleExport}
        >
          {t("common.download")}
        </Button>,
      ]}
    >
      <CheckboxMultiSelectList
        items={items}
        selectedKeys={selectedKeys}
        onChange={handleSelectionChange}
        withSelectAll
      />
    </Modal>
  );
}
