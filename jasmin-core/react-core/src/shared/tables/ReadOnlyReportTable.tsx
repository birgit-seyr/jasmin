import { Table } from "antd";
import type { TableProps } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { EmptyHint } from "@shared/ui";

/**
 * Lightweight read-only report table: a thin wrapper over AntD ``Table`` that
 * bakes in the shared ``custom-jasmin-table`` class, ``size="small"`` and the
 * subtle-grey ``EmptyHint`` empty state — the scaffolding that read-only
 * reports across members/abos/gdpr were copy-pasting.
 *
 * This is intentionally NOT ``EditableTable``: server-paginated tables and
 * tables with custom action columns (approve / reject / download) belong here,
 * not forced through the full editable grid. Every other AntD ``Table`` prop
 * (``columns`` / ``dataSource`` / ``rowKey`` / ``loading`` / ``pagination`` /
 * ``rowClassName`` / ``locale`` / …) passes straight through.
 */
export interface ReadOnlyReportTableProps<T> extends TableProps<T> {
  /**
   * Message shown (wrapped in ``<EmptyHint>``) when there are no rows. Defaults
   * to the shared "no data" copy. A caller-supplied ``locale.emptyText`` still
   * wins over this.
   */
  emptyText?: ReactNode;
}

export default function ReadOnlyReportTable<T extends object>({
  className = "custom-jasmin-table",
  size = "small",
  emptyText,
  locale,
  ...rest
}: ReadOnlyReportTableProps<T>) {
  const { t } = useTranslation();

  return (
    <Table<T>
      className={className}
      size={size}
      locale={{
        emptyText: <EmptyHint>{emptyText ?? t("table.no_data")}</EmptyHint>,
        ...locale,
      }}
      {...rest}
    />
  );
}
