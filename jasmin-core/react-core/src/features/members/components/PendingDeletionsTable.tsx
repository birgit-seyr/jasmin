import {
  CheckOutlined,
  CloseOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Space, Table, Tag, Tooltip, Typography } from "antd";
import { EmptyHint } from "@shared/ui";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  getGdprAdminDecidedDeletionsListQueryKey,
  getGdprAdminPendingDeletionsRetrieveQueryKey,
  useGdprAdminApproveDeletionCreate,
  useGdprAdminPendingDeletionsRetrieve,
} from "@shared/api/generated/gdpr/gdpr";
import type { AdminPendingDeletion } from "@shared/api/generated/models";
import { useTimeFormat } from "@hooks/index";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";

const { Paragraph } = Typography;

interface PendingDeletionsTableProps {
  /** Opens the parent's reject-with-reason modal for the given row. */
  onRejectRequested: (row: AdminPendingDeletion) => void;
}

/**
 * Admin inbox of GDPR deletion requests in ``PENDING_ADMIN``.
 *
 * Owns its own query + approve mutation. The reject flow is parent-
 * driven because the reject reason modal is shared with potentially
 * other entry points later — this table just bubbles "user clicked
 * Ablehnen on this row" upward.
 */
export default function PendingDeletionsTable({
  onRejectRequested,
}: PendingDeletionsTableProps) {
  const { t } = useTranslation();
  const { formatDateTime } = useTimeFormat();
  const queryClient = useQueryClient();

  const { data, isFetching } = useGdprAdminPendingDeletionsRetrieve();
  const pending: AdminPendingDeletion[] = data?.pending ?? [];

  const { mutate: approveMutate, variables: approvingVars } =
    useGdprAdminApproveDeletionCreate({
      mutation: {
        onSuccess: () => {
          notify.success(t("gdpr.approved"));
          // Both lists are now stale: the approved row leaves pending
          // and shows up in decided.
          queryClient.invalidateQueries({
            queryKey: getGdprAdminPendingDeletionsRetrieveQueryKey(),
          });
          queryClient.invalidateQueries({
            queryKey: getGdprAdminDecidedDeletionsListQueryKey(),
          });
        },
        onError: (error) => {
          notify.error(getErrorMessage(error, "Failed to approve"));
        },
      },
    });
  const approvingId = approvingVars?.requestId;

  const columns = useMemo(
    () => [
      {
        title: t("gdpr.requested_email"),
        dataIndex: "requested_email",
        key: "requested_email",
        render: (val: string, row: AdminPendingDeletion) =>
          row.current_user_email && row.current_user_email !== val ? (
            <Space direction="vertical" size={0}>
              <span>{val}</span>
              <Tag color="orange">
                {t("gdpr.email_changed_since", {
                  email: row.current_user_email,
                })}
              </Tag>
            </Space>
          ) : (
            val
          ),
      },
      {
        title: t("gdpr.requested_at"),
        dataIndex: "requested_at",
        key: "requested_at",
        render: (val: string) => formatDateTime(val) ?? "—",
      },
      {
        title: t("gdpr.email_confirmed_at"),
        dataIndex: "email_confirmed_at",
        key: "email_confirmed_at",
        render: (val: string | null) =>
          val ? (formatDateTime(val) ?? "—") : "—",
      },
      {
        title: t("gdpr.blockers"),
        dataIndex: "blockers",
        key: "blockers",
        render: (blockers: string[] | undefined) => {
          const list = blockers ?? [];
          return list.length === 0 ? (
            <Tag color="green">{t("gdpr.ready")}</Tag>
          ) : (
            <Space direction="vertical" size={2}>
              {list.map((reason, i) => (
                <Tag key={i} color="orange" style={{ whiteSpace: "normal" }}>
                  {reason}
                </Tag>
              ))}
            </Space>
          );
        },
      },
      {
        title: "",
        key: "actions",
        align: "right" as const,
        render: (_: unknown, row: AdminPendingDeletion) => {
          const blocked = (row.blockers?.length ?? 0) > 0;
          const acting = approvingId === row.id;
          return (
            <Space>
              <Tooltip title={blocked ? t("gdpr.approve_blocked_tooltip") : ""}>
                <Button
                  type="primary"
                  icon={<CheckOutlined />}
                  loading={acting}
                  disabled={blocked}
                  onClick={() => approveMutate({ requestId: row.id })}
                >
                  {t("gdpr.approve")}
                </Button>
              </Tooltip>
              <Button
                danger
                icon={<CloseOutlined />}
                disabled={acting}
                onClick={() => onRejectRequested(row)}
              >
                {t("gdpr.reject")}
              </Button>
            </Space>
          );
        },
      },
    ],
    [t, formatDateTime, approvingId, approveMutate, onRejectRequested],
  );

  return (
    <div>
      <div className="flex-between" style={{ marginBottom: "0.5em" }}>
        <h3>
          <Space>
            {t("gdpr.pending_deletions")}
            {pending.length > 0 && <Tag color="orange">{pending.length}</Tag>}
          </Space>
        </h3>
      </div>
      <Paragraph type="secondary">
        {t("gdpr.pending_deletions_description")}
      </Paragraph>

      <Table
        className="custom-jasmin-table"
        columns={columns}
        dataSource={pending}
        rowKey="id"
        pagination={false}
        size="small"
        loading={isFetching}
        locale={{ emptyText: <EmptyHint>{t("gdpr.no_pending")}</EmptyHint> }}
      />
    </div>
  );
}
