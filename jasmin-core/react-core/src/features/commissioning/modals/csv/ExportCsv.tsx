import { useState, useMemo, useCallback, isValidElement } from "react";
import type { ReactNode } from "react";
import { Modal, Button, Checkbox } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import {
  buildCsvString,
  downloadCsvBlob,
  resolveCsvDialect,
} from "@shared/utils";
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
    return flatCols;
  }, [columns]);

  const [selectedKeys, setSelectedKeys] = useState<string[]>(() =>
    exportableColumns.map((c) => c.dataIndex as string),
  );

  const allSelected = selectedKeys.length === exportableColumns.length;
  const noneSelected = selectedKeys.length === 0;

  const handleToggleAll = useCallback(() => {
    if (allSelected) {
      setSelectedKeys([]);
    } else {
      setSelectedKeys(exportableColumns.map((c) => c.dataIndex as string));
    }
  }, [allSelected, exportableColumns]);

  const handleToggle = useCallback((key: string) => {
    setSelectedKeys((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
    );
  }, []);

  const handleExport = useCallback(() => {
    const selectedCols = exportableColumns.filter((col) =>
      selectedKeys.includes(col.dataIndex as string),
    );

    const headers = selectedCols.map((col) => getColumnTitle(col.title));
    const rows = data.map((row) =>
      selectedCols.map((col) => row[col.dataIndex as string]),
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
      <div style={{ marginBottom: 12 }}>
        <Checkbox
          checked={allSelected}
          indeterminate={!allSelected && !noneSelected}
          onChange={handleToggleAll}
        >
          <strong>{t("common.select_all")}</strong>
        </Checkbox>
      </div>
      <div
        style={{
          maxHeight: 300,
          overflowY: "auto",
          border: "1px solid var(--color-border)",
          borderRadius: 6,
          padding: 12,
        }}
      >
        {exportableColumns.map((col) => (
          <div key={col.dataIndex as string} style={{ padding: "4px 0" }}>
            <Checkbox
              checked={selectedKeys.includes(col.dataIndex as string)}
              onChange={() => handleToggle(col.dataIndex as string)}
            >
              {getColumnTitle(col.title)}
            </Checkbox>
          </div>
        ))}
      </div>
    </Modal>
  );
}
