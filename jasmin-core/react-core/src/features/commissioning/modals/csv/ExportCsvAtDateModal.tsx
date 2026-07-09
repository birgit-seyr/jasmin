import { useState, useCallback, useMemo } from "react";
import { Modal, DatePicker, Button, Spin } from "antd";
import { EmptyHint } from "@shared/ui";
import { DownloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import dayjs, { Dayjs } from "dayjs";
import {
  buildCsvString,
  downloadCsvBlob,
  resolveCsvDialect,
  toApiDate,
} from "@shared/utils";
import { useTenant, useDateFormat } from "@hooks/index";

export interface PriceColumn {
  key: string;
  label: string;
}

export interface ExportCsvColumn {
  key: string;
  label: string;
  /** Optional per-cell value transform (boolean → ja/nein, null → "", …). */
  render?: (value: unknown, row: Record<string, unknown>) => unknown;
}

/**
 * Supplier hook: given the loaded date (or null before Load), returns the CSV
 * row stream and its loading flag. Each consumer wires its own generated
 * `useXxxList` query (and any client-side merge / filter) here.
 */
export type UseRowsAtDate = (loadedDate: string | null) => {
  rows: Record<string, unknown>[] | null;
  isLoading: boolean;
};

export interface ExportCsvAtDateModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  filenamePrefix: string;
  columns: ExportCsvColumn[];
  useRows: UseRowsAtDate;
  width?: number;
  /** i18n key for the "N rows loaded" success line (receives `{ count }`). */
  loadedMessageKey?: string;
}

/**
 * Generic CSV export modal for "list at a specific date" endpoints. The user
 * picks a date, presses Load (which feeds `useRows`), then Download builds a
 * CSV client-side (honoring each column's optional `render`).
 */
export default function ExportCsvAtDateModal({
  open,
  onClose,
  title,
  filenamePrefix,
  columns,
  useRows,
  width = 420,
  loadedMessageKey = "commissioning.prices_loaded",
}: ExportCsvAtDateModalProps) {
  const { t } = useTranslation();
  const { getSetting } = useTenant();
  const { dateFormat } = useDateFormat();
  const dialect = useMemo(
    () => resolveCsvDialect(getSetting("csv_format", "de") as string),
    [getSetting],
  );
  const [selectedDate, setSelectedDate] = useState<Dayjs>(dayjs());
  const [loadedDate, setLoadedDate] = useState<string | null>(null);

  const { rows: rawRows, isLoading: loading } = useRows(loadedDate);

  const rows = useMemo<Record<string, unknown>[] | null>(
    () => (loadedDate ? (rawRows ?? null) : null),
    [rawRows, loadedDate],
  );

  const fetchRows = useCallback(() => {
    if (!selectedDate) return;
    setLoadedDate(toApiDate(selectedDate));
  }, [selectedDate]);

  const handleExport = useCallback(() => {
    if (!rows || rows.length === 0) return;
    const headers = columns.map((c) => c.label);
    const csvRows = rows.map((row) =>
      columns.map((c) => {
        const raw = row[c.key];
        return c.render ? c.render(raw, row) : (raw ?? "");
      }),
    );
    downloadCsvBlob(
      buildCsvString(headers, csvRows, dialect),
      `${filenamePrefix}_${selectedDate.format("YYYY-MM-DD")}`,
    );
    onClose();
  }, [rows, columns, selectedDate, filenamePrefix, onClose, dialect]);

  const handleClose = useCallback(() => {
    setLoadedDate(null);
    onClose();
  }, [onClose]);

  return (
    <Modal
      title={title}
      open={open}
      onCancel={handleClose}
      width={width}
      footer={[
        <Button key="cancel" onClick={handleClose}>
          {t("common.cancel")}
        </Button>,
        <Button
          key="export"
          type="primary"
          className="download-button"
          icon={<DownloadOutlined />}
          disabled={!rows || rows.length === 0}
          onClick={handleExport}
        >
          {t("common.download")}
        </Button>,
      ]}
    >
      <div className="flex-center-y gap-12" style={{ marginBottom: 16 }}>
        <DatePicker
          value={selectedDate}
          onChange={(date) => {
            if (date) setSelectedDate(date);
          }}
          format={dateFormat}
          className="flex-1"
        />
        <Button type="primary" onClick={fetchRows} loading={loading}>
          {t("common.load")}
        </Button>
      </div>

      {loading && (
        <div style={{ textAlign: "center", padding: 24 }}>
          <Spin />
        </div>
      )}

      {!loading && rows && rows.length === 0 && (
        <EmptyHint>{t("common.no_data")}</EmptyHint>
      )}

      {!loading && rows && rows.length > 0 && (
        <div style={{ color: "var(--color-success)", fontWeight: 500 }}>
          {t(loadedMessageKey, { count: rows.length })}
        </div>
      )}
    </Modal>
  );
}
