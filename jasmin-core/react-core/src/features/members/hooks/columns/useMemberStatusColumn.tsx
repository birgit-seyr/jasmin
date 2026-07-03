import { Tag, Tooltip } from "antd";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { useDateFormat } from "@hooks/index";

/**
 * Membership-status column for the members table.
 *
 * A Member is NOT a time-bounded subscription — it has no
 * ``valid_from``/``valid_until``. Its lifecycle is ``entry_date`` (admission to
 * the Mitgliederliste) → ``cancelled_effective_at`` (legal exit date). The
 * generic ``useActiveStatusColumn`` (built for valid_from/valid_until rows)
 * therefore reports a meaningless "always active" for members; this derives the
 * real state from the fields a Member actually has.
 */
type MemberStatus =
  | "rejected"
  | "left"
  | "leaving"
  | "pending"
  | "trial"
  | "active";

interface MemberStatusFields {
  admin_rejected_at?: string | null;
  admin_confirmed?: boolean | null;
  is_trial?: boolean | null;
  cancelled_at?: string | null;
  cancelled_effective_at?: string | null;
  entry_date?: string | null;
}

// First match wins. Mirrors the backend's terminal "cancelled_at is not None"
// check and the row striping in Members.tsx.
function deriveStatus(r: MemberStatusFields, today: string): MemberStatus {
  if (r.admin_rejected_at) return "rejected";
  if (r.cancelled_at) {
    // Notice served: still a member until the exit date, then gone. Dates are
    // "YYYY-MM-DD" so lexicographic compare == chronological.
    if (r.cancelled_effective_at && r.cancelled_effective_at > today)
      return "leaving";
    return "left";
  }
  if (!r.admin_confirmed) return "pending";
  if (r.is_trial) return "trial";
  return "active";
}

// Sort rank: most-active first under defaultSortOrder "descend".
const STATUS_RANK: Record<MemberStatus, number> = {
  active: 5,
  trial: 4,
  pending: 3,
  leaving: 2,
  left: 1,
  rejected: 0,
};

const STATUS_TAG: Record<MemberStatus, { color: string; labelKey: string }> = {
  active: { color: "success", labelKey: "members.status_active" },
  trial: { color: "cyan", labelKey: "members.status_trial" },
  pending: { color: "processing", labelKey: "members.status_pending" },
  leaving: { color: "warning", labelKey: "members.status_cancelled" },
  left: { color: "default", labelKey: "members.status_cancelled" },
  rejected: { color: "default", labelKey: "members.status_rejected" },
};

export const useMemberStatusColumn = () => {
  const { t } = useTranslation();
  const { formatDate } = useDateFormat();

  return useMemo<EditableColumnConfig<TableRecord>>(() => {
    const today = new Date().toISOString().slice(0, 10);
    return {
      title: t("members.current_status"),
      dataIndex: "is_active",
      key: "is_active",
      align: "center",
      readOnly: true,
      disabled: true,
      width: "7em",
      showSorterTooltip: false,
      defaultSortOrder: "descend",
      sorter: (a: TableRecord, b: TableRecord) =>
        STATUS_RANK[deriveStatus(a as MemberStatusFields, today)] -
        STATUS_RANK[deriveStatus(b as MemberStatusFields, today)],
      render: (_value: unknown, record: TableRecord) => {
        const r = record as MemberStatusFields;
        const status = deriveStatus(r, today);
        const { color, labelKey } = STATUS_TAG[status];

        let tip: string | undefined;
        if (
          (status === "leaving" || status === "left") &&
          r.cancelled_effective_at
        ) {
          tip = t("members.member_cancelled_title", {
            date: formatDate(r.cancelled_effective_at),
          });
        } else if (r.entry_date) {
          tip = `${t("members.entry_date")}: ${formatDate(r.entry_date)}`;
        }

        const tag = <Tag color={color}>{t(labelKey)}</Tag>;
        return tip ? <Tooltip title={tip}>{tag}</Tooltip> : tag;
      },
    };
  }, [t, formatDate]);
};
