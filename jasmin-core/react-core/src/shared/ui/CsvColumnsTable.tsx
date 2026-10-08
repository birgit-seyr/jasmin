import { Table } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

export interface CsvColumnHelp {
  /** The CSV header exactly as the importer expects it. */
  field: string;
  required: boolean;
  meaning: ReactNode;
}

/**
 * The help table an import dialog shows for the columns its CSV takes: each
 * header, whether it is required and what it means. Keyed by the header,
 * which a CSV can carry only once.
 */
export default function CsvColumnsTable({ rows }: { rows: CsvColumnHelp[] }) {
  const { t } = useTranslation();
  return (
    <Table<CsvColumnHelp>
      size="small"
      pagination={false}
      rowKey="field"
      dataSource={rows}
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
  );
}
