import { ReloadOutlined } from "@ant-design/icons";
import { Button, Card, Space, Table, Tag, Typography } from "antd";
import { EmptyHint } from "@shared/ui";
import type { TFunction } from "i18next";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useGdprAdminDecidedDeletionsList } from "@shared/api/generated/gdpr/gdpr";
import type { AdminDecidedDeletion } from "@shared/api/generated/models";
import { useTimeFormat } from "@hooks/index";

const { Paragraph } = Typography;

const HISTORY_PAGE_SIZE = 20;

// Backend emits ``state`` as a free-form string (the underlying
// ``DeletionRequestState`` choices). Narrow at the boundary so the
// tag lookup is exhaustive and any future state value falls through
// to the neutral default.
type DecidedState = "rejected" | "executed" | "cancelled" | "expired";

const STATE_TAG_COLOR: Record<DecidedState, string> = {
  rejected: "red",
  executed: "purple",
  cancelled: "default",
  expired: "default",
};

const stateTagLabel = (state: DecidedState, t: TFunction) =>
  ({
    rejected: t("gdpr.state_rejected"),
    executed: t("gdpr.state_executed"),
    cancelled: t("gdpr.state_cancelled"),
    expired: t("gdpr.state_expired"),
  })[state];

/**
 * History of every deletion request no longer awaiting action —
 * REJECTED, EXECUTED, CANCELLED, EXPIRED. Paginated server-side via
 * the project-standard ``OptionalLimitOffsetPagination``.
 */
export default function DecidedDeletionsCard() {
  const { t } = useTranslation();
  const { formatDateTime } = useTimeFormat();
  const [page, setPage] = useState(1);

  const { data, isFetching, refetch } = useGdprAdminDecidedDeletionsList({
    limit: HISTORY_PAGE_SIZE,
    offset: (page - 1) * HISTORY_PAGE_SIZE,
  });
  // ``OptionalLimitOffsetPagination`` returns ``{count, results}`` at
  // runtime when ``limit`` is passed (always, here). Orval types
  // ``data`` as the bare row list because that's what the schema
  // declares — see ``OptionalLimitOffsetPagination.get_paginated_response_schema``.
  // The cast bridges that project-wide gap.
  const payload = data as
    | { count?: number; results?: AdminDecidedDeletion[] }
    | undefined;
  const rows = payload?.results ?? [];
  const total = payload?.count ?? 0;

  const columns = useMemo(
    () => [
      {
        title: t("gdpr.state"),
        dataIndex: "state",
        key: "state",
        width: 130,
        render: (state: string) => {
          // Narrow at the column boundary; unknown future values
          // fall through to the neutral grey tag.
          const known = state as DecidedState;
          return (
            <Tag color={STATE_TAG_COLOR[known] ?? "default"}>
              {stateTagLabel(known, t) ?? state}
            </Tag>
          );
        },
      },
      {
        title: t("gdpr.requested_email"),
        dataIndex: "requested_email",
        key: "requested_email",
      },
      {
        title: t("gdpr.requested_at"),
        dataIndex: "requested_at",
        key: "requested_at",
        render: (val: string) => formatDateTime(val) ?? "—",
      },
      {
        title: t("gdpr.decided_at"),
        dataIndex: "decided_at",
        key: "decided_at",
        render: (val: string | null) =>
          val ? (formatDateTime(val) ?? "—") : "—",
      },
      {
        title: t("gdpr.decided_by"),
        dataIndex: "decided_by_email",
        key: "decided_by_email",
        render: (val: string | null) => val ?? "—",
      },
      {
        title: t("gdpr.rejection_reason"),
        dataIndex: "rejection_reason",
        key: "rejection_reason",
        render: (val: string | null) =>
          val ? (
            <Typography.Text style={{ whiteSpace: "pre-wrap" }}>
              {val}
            </Typography.Text>
          ) : (
            "—"
          ),
      },
    ],
    [t, formatDateTime],
  );

  return (
    <Card
      className="settings-card-header"
      title={
        <Space>
          {t("gdpr.decided_deletions")}
          {total > 0 && <Tag>{total}</Tag>}
        </Space>
      }
      extra={
        <Button
          icon={<ReloadOutlined />}
          onClick={() => refetch()}
          loading={isFetching}
          size="small"
        >
          {t("common.refresh")}
        </Button>
      }
      style={{ width: "100%" }}
    >
      {rows.length === 0 && !isFetching ? (
        <EmptyHint>{t("gdpr.no_decided")}</EmptyHint>
      ) : (
        <Table
          columns={columns}
          dataSource={rows}
          rowKey="id"
          size="small"
          loading={isFetching}
          pagination={{
            current: page,
            pageSize: HISTORY_PAGE_SIZE,
            total,
            onChange: (next) => setPage(next),
            showSizeChanger: false,
          }}
        />
      )}
    </Card>
  );
}
