import { useState, useCallback, useMemo } from "react";
import { Modal, DatePicker, Button, Spin, Empty } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import dayjs, { Dayjs } from "dayjs";
import {
  buildCsvString,
  downloadCsvBlob,
  resolveCsvDialect,
} from "@shared/utils";
import { useTenant, useDateFormat } from "@hooks/index";

export interface PriceColumn {
  key: string;
  label: string;
}

/**
 * Loose shape of the orval-generated `useXxxList` query hooks: takes a params
 * object plus a react-query options envelope, returns `{ data, isLoading }`.
 */
export type UseListAtDateHook<T> = (
  params: { active_at_date: string },
  options: { query: { enabled: boolean } },
) => { data: T[] | undefined; isLoading: boolean };

export interface ExportCsvAtDateModalProps<T> {
  open: boolean;
  onClose: () => void;
  title: string;
  filenamePrefix: string;
  columns: PriceColumn[];
  useListAtDate: UseListAtDateHook<T>;
  width?: number;
}

/**
 * Generic CSV export modal for "list at a specific date" endpoints. The user
 * picks a date, presses Load, then Download builds a CSV client-side.
 */
export default function ExportCsvAtDateModal<T>({
  open,
  onClose,
  title,
  filenamePrefix,
  columns,
  useListAtDate,
  width = 420,
}: ExportCsvAtDateModalProps<T>) {
  const { t } = useTranslation();
  const { getSetting } = useTenant();
  const { dateFormat } = useDateFormat();
  const dialect = useMemo(
    () => resolveCsvDialect(getSetting("csv_format", "de") as string),
    [getSetting],
  );
  const [selectedDate, setSelectedDate] = useState<Dayjs>(dayjs());
  const [loadedDate, setLoadedDate] = useState<string | null>(null);

  const { data: rawData, isLoading: loading } = useListAtDate(
    { active_at_date: loadedDate ?? "" },
    { query: { enabled: !!loadedDate } },
  );

  const data = useMemo<T[] | null>(
    () => (loadedDate ? (rawData ?? null) : null),
    [rawData, loadedDate],
  );

  const fetchPrices = useCallback(() => {
    if (!selectedDate) return;
    setLoadedDate(selectedDate.format("YYYY-MM-DD"));
  }, [selectedDate]);

  const handleExport = useCallback(() => {
    if (!data || data.length === 0) return;
    const headers = columns.map((c) => c.label);
    const rows = data.map((row) =>
      columns.map((c) => (row as Record<string, unknown>)[c.key]),
    );
    downloadCsvBlob(
      buildCsvString(headers, rows, dialect),
      `${filenamePrefix}_${selectedDate.format("YYYY-MM-DD")}`,
    );
    onClose();
  }, [data, columns, selectedDate, filenamePrefix, onClose, dialect]);

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
          disabled={!data || data.length === 0}
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
        <Button type="primary" onClick={fetchPrices} loading={loading}>
          {t("common.load")}
        </Button>
      </div>

      {loading && (
        <div style={{ textAlign: "center", padding: 24 }}>
          <Spin />
        </div>
      )}

      {!loading && data && data.length === 0 && (
        <Empty description={t("common.no_data")} />
      )}

      {!loading && data && data.length > 0 && (
        <div style={{ color: "var(--color-success)", fontWeight: 500 }}>
          {t("commissioning.prices_loaded", { count: data.length })}
        </div>
      )}
    </Modal>
  );
}
