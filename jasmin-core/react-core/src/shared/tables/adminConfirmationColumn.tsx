import type { TFunction } from "i18next";
import { StatusButton } from "@shared/ui";
import type { EditableColumnConfig, TableRecord } from "./BasicEditableTable/types";

export interface AdminStatusVariant {
  /** StatusButton variant: "adminConfirmed" | "adminPending" | "adminRejected". */
  variant: string;
  /** i18n suffix under ``members.*`` used for the status tooltip
   * (e.g. "admin_confirmed" → ``members.admin_confirmed``). */
  key: string;
}

interface AdminConfirmationColumnOptions<T> {
  t: TFunction;
  /** Map a row to its admin-confirmation status (button variant + tooltip key). */
  getAdminStatus: (record: T) => AdminStatusVariant;
  /** Open the admin-confirmation modal for the clicked row. */
  onOpen: (record: T) => void;
  /** Optional sorter; when given, the sort chevron + showSorterTooltip:false
   *  are wired (the column stays sortable). */
  sorter?: (a: T, b: T, sortOrder?: "ascend" | "descend") => number;
  /** Column width — default "4em" (fits the rotated vertical title). */
  width?: string;
  /** Title i18n key — default "members.admin_status". */
  titleKey?: string;
}

/**
 * Shared "admin confirmation" status column: a rotated (vertical)
 * ``checkbox-column-title`` header + a {@link StatusButton} whose icon/colour
 * reflects the row's confirmation status; clicking it opens the
 * admin-confirmation modal. Reused by the members table, the abos table, and
 * the coop-shares modal so all three look + behave identically. The inline-edit
 * placeholder row (``key === -1``) and any row currently being edited disable
 * the button (you can't confirm a half-typed draft).
 */
export function adminConfirmationColumn<T extends TableRecord>({
  t,
  getAdminStatus,
  onOpen,
  sorter,
  width = "4em",
  titleKey = "members.admin_status",
}: AdminConfirmationColumnOptions<T>): EditableColumnConfig<T> {
  return {
    title: <div className="checkbox-column-title">{t(titleKey)}</div>,
    dataIndex: "admin_confirmed",
    key: "admin_confirmed",
    align: "center" as const,
    width,
    // EditableTable flags: this column is never inline-editable.
    disabled: true,
    readOnly: true,
    render: (_value: unknown, record: T) => {
      const status = getAdminStatus(record);
      const isEditing = record.key === -1 || Boolean(record.isEditing);
      return (
        <StatusButton
          variant={status.variant}
          onClick={() => !isEditing && onOpen(record)}
          tooltip={isEditing ? "" : t(`members.${status.key}`)}
          showTooltip
          disabled={isEditing}
        />
      );
    },
    ...(sorter ? { sorter, showSorterTooltip: false } : {}),
  };
}
