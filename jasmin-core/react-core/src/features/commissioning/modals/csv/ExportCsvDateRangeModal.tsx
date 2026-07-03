import { DownloadOutlined } from "@ant-design/icons";
import { Button, Checkbox, DatePicker, Modal, Space } from "antd";
import type { Dayjs } from "dayjs";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { useDateFormat, useDateRangePresets } from "@hooks/index";
import { downloadCsvBlob } from "@shared/utils";

const { RangePicker } = DatePicker;

export interface ExportCsvDateRangeOption {
  /** Identifier appended to the params object as `{ [key]: boolean }`. */
  key: string;
  /** Visible label next to the checkbox. */
  label: string;
  /** When checked, this string is appended to the filename. */
  filenameSuffix?: string;
  /** Optional initial checked state. */
  defaultChecked?: boolean;
}

export interface ExportCsvDateRangeModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  /** Filename prefix (date range will be appended). */
  filenamePrefix: string;
  /**
   * Function that fetches the raw CSV string from the backend given the
   * date range and any toggled boolean options.
   */
  fetchCsv: (
    params: { date_from: string; date_to: string } & Record<string, unknown>,
  ) => Promise<unknown>;
  /** Optional list of boolean checkboxes shown below the date picker. */
  options?: ExportCsvDateRangeOption[];
  /** Modal width. Defaults to 450. */
  width?: number;
}

/**
 * Generic CSV export modal for endpoints that accept a date range
 * and produce a CSV string server-side. The backend honors the tenant's
 * ``csv_format`` static setting (delimiter, decimal separator, date format).
 */
export default function ExportCsvDateRangeModal({
  open,
  onClose,
  title,
  filenamePrefix,
  fetchCsv,
  options = [],
  width = 450,
}: ExportCsvDateRangeModalProps) {
  const { t } = useTranslation();
  const { dateFormat } = useDateFormat();
  const presets = useDateRangePresets();
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [optionState, setOptionState] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(options.map((o) => [o.key, o.defaultChecked ?? false])),
  );
  const [loading, setLoading] = useState(false);

  const handleExport = useCallback(async () => {
    if (!dateRange) return;
    const [from, to] = dateRange;
    const params = {
      date_from: from.format("YYYY-MM-DD"),
      date_to: to.format("YYYY-MM-DD"),
      ...optionState,
    };
    try {
      setLoading(true);
      const csvData = await fetchCsv(params);
      let filename = `${filenamePrefix}_${from.format("YYYY-MM-DD")}_${to.format("YYYY-MM-DD")}`;
      for (const opt of options) {
        if (optionState[opt.key] && opt.filenameSuffix) {
          filename += opt.filenameSuffix;
        }
      }
      downloadCsvBlob(csvData as BlobPart, filename);
      onClose();
    } catch (error) {
      console.error("Export failed:", error);
    } finally {
      setLoading(false);
    }
  }, [dateRange, optionState, fetchCsv, filenamePrefix, options, onClose]);


  const handleClose = useCallback(() => {
    setDateRange(null);
    setOptionState(
      Object.fromEntries(options.map((o) => [o.key, o.defaultChecked ?? false])),
    );
    onClose();
  }, [onClose, options]);

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
          icon={<DownloadOutlined />}
          disabled={!dateRange}
          loading={loading}
          onClick={handleExport}
        >
          {t("common.download")}
        </Button>,
      ]}
    >
      <Space direction="vertical" size="middle" className="w-full">
        <div>
          <div style={{ marginBottom: 8 }}>
            {t("common.select_date_range")}
          </div>
          <RangePicker
            value={dateRange}
            onChange={(dates) => setDateRange(dates as [Dayjs, Dayjs] | null)}
            format={dateFormat}
            className="w-full"
            presets={presets}
          />
        </div>

        {options.map((opt) => (
          <Checkbox
            key={opt.key}
            checked={!!optionState[opt.key]}
            onChange={(e) =>
              setOptionState((prev) => ({
                ...prev,
                [opt.key]: e.target.checked,
              }))
            }
          >
            {opt.label}
          </Checkbox>
        ))}
      </Space>
    </Modal>
  );
}
