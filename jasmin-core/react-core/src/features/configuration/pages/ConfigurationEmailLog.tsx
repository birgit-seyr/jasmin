import { Input, Select, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { EmailLog } from "@shared/api/generated/models";
import { useNotificationsEmailLogsList } from "@shared/api/generated/notifications/notifications";
import { useTimeFormat } from "@hooks/index";
import { getEmailStatusColor } from "@shared/utils/emailStatusColors";

const ALL_STATUSES = [
  "pending",
  "sent",
  "delivered",
  "bounced",
  "deferred",
  "complained",
  "rejected",
  "failed",
] as const;

const ALL_PURPOSES = [
  "accounts.invitation",
  "accounts.password_reset",
  "accounts.application_received",
  "accounts.application_approved",
  "accounts.application_rejected",
  "accounts.welcome_user",
  "commissioning.trial_converted",
  "commissioning.member_cancelled",
  "commissioning.offer",
  "commissioning.invoice",
  "commissioning.delivery_note",
  "commissioning.invoice_reminder",
  "gdpr.deletion_confirm",
  "gdpr.deletion_approved",
  "gdpr.deletion_rejected",
] as const;

export default function ConfigurationEmailLog() {
  const { t } = useTranslation();
  const { formatDateTime } = useTimeFormat();

  const [recipientFilter, setRecipientFilter] = useState("");
  const [purposeFilter, setPurposeFilter] = useState<string | undefined>(
    undefined,
  );
  const [statusFilter, setStatusFilter] = useState<string | undefined>(
    undefined,
  );

  const params = useMemo(() => {
    const p: Record<string, string> = {};
    if (recipientFilter.trim()) p.recipient = recipientFilter.trim();
    if (purposeFilter) p.purpose = purposeFilter;
    if (statusFilter) p.status = statusFilter;
    return p;
  }, [recipientFilter, purposeFilter, statusFilter]);

  // ``isFetching`` (not ``isLoading``): filter changes alter the query key,
  // and with the global ``staleTime: 0`` a revisited filter combination is
  // cached (``isLoading === false``) — only ``isFetching`` shows the spinner
  // while the refetch runs, instead of silently displaying stale rows.
  const { data, isFetching } = useNotificationsEmailLogsList(params);

  const rows = useMemo<EmailLog[]>(
    () => (Array.isArray(data) ? data : []),
    [data],
  );

  const columns = useMemo<ColumnsType<EmailLog>>(
    () => [
      {
        title: t("logging.created"),
        dataIndex: "created_at",
        key: "created_at",
        width: "11em",
        defaultSortOrder: "descend",
        sorter: (a, b) =>
          (a.created_at ?? "").localeCompare(b.created_at ?? ""),
        render: (value: string) => formatDateTime(value),
      },
      {
        title: t("email_matrix.recipient"),
        dataIndex: "recipient",
        key: "recipient",
        ellipsis: true,
      },
      {
        title: t("email_matrix.subject"),
        dataIndex: "subject",
        key: "subject",
        ellipsis: true,
      },
      {
        title: t("email_matrix.purpose"),
        dataIndex: "purpose",
        key: "purpose",
        render: (value: string) => t(`email_matrix.${value}`),
      },
      {
        title: t("email_matrix.status_col"),
        dataIndex: "status",
        key: "status",
        width: "9em",
        render: (value: string) => (
          <Tag color={getEmailStatusColor(value)}>
            {t(`email_matrix.status.${value}`)}
          </Tag>
        ),
      },
      {
        title: t("email_matrix.sent_at"),
        dataIndex: "sent_at",
        key: "sent_at",
        width: "11em",
        render: (value: string | null) =>
          value ? formatDateTime(value) : "—",
      },
    ],
    [t, formatDateTime],
  );

  return (
    <div>
      <div className="filter-bar">
        <Input
          placeholder={t("email_matrix.recipient")}
          value={recipientFilter}
          onChange={(e) => setRecipientFilter(e.target.value)}
          allowClear
          style={{ width: 220 }}
        />
        <Select
          placeholder={t("email_matrix.purpose")}
          value={purposeFilter}
          onChange={setPurposeFilter}
          allowClear
          style={{ width: 220 }}
          options={ALL_PURPOSES.map((p) => ({
            value: p,
            label: t(`email_matrix.${p}`),
          }))}
        />
        <Select
          placeholder={t("email_matrix.status_col")}
          value={statusFilter}
          onChange={setStatusFilter}
          allowClear
          style={{ width: 160 }}
          options={ALL_STATUSES.map((s) => ({
            value: s,
            label: t(`email_matrix.status.${s}`),
          }))}
        />
      </div>

      <Table<EmailLog>
        columns={columns}
        dataSource={rows}
        rowKey="id"
        loading={isFetching}
        pagination={{ pageSize: 50, showSizeChanger: true }}
        size="small"
        locale={{
          emptyText: t("members.no_emails_sent"),
        }}
      />
    </div>
  );
}
