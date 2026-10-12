import {
  CheckOutlined,
  CloseOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Space, Tag, Tooltip, Typography } from "antd";
import { ReadOnlyReportTable } from "@shared/tables";
import { useMemo, useState } from "react";
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

import ApproveDeletionModal from "../modals/ApproveDeletionModal";

const { Paragraph } = Typography;

interface PendingDeletionsTableProps {
  /** Opens the parent's reject-with-reason modal for the given row. */
  onRejectRequested: (row: AdminPendingDeletion) => void;
}

/**
 * Admin inbox of GDPR deletion requests in ``PENDING_ADMIN``.
 *
 * Owns its own query + approve mutation; Approve opens a modal showing what
 * the erasure would delete before it runs. The reject flow is parent-
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
  const [approveTarget, setApproveTarget] =
    useState<AdminPendingDeletion | null>(null);

  const { mutate: approveMutate, isPending: approving } =
    useGdprAdminApproveDeletionCreate({
      mutation: {
        meta: { silent: true },
        onSuccess: () => {
          notify.success(t("gdpr.approved"));
          setApproveTarget(null);
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
          notify.error(getErrorMessage(error));
        },
      },
    });

  const columns = useMemo(
    () => [
      {
        title: t("gdpr.subject"),
        dataIndex: "subject_label",
        key: "subject_label",
        render: (label: string, row: AdminPendingDeletion) => (
          <Space direction="vertical" size={0}>
            <span>{label}</span>
            {row.channel !== "self_service" && (
              <Tag>
                {t("gdpr.filed_by_office", {
                  channel: t(`gdpr.channel.${row.channel}`),
                })}
              </Tag>
            )}
            {row.current_user_email &&
              row.current_user_email !== row.requested_email && (
                <Tag color="orange">
                  {t("gdpr.email_changed_since", {
                    email: row.current_user_email,
                  })}
                </Tag>
              )}
          </Space>
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
        render: (blockers: string[]) => {
          return blockers.length === 0 ? (
            <Tag color="green">{t("gdpr.ready")}</Tag>
          ) : (
            <Space direction="vertical" size={2}>
              {blockers.map((reason, i) => (
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
          const blocked = row.blockers.length > 0;
          return (
            <Space>
              <Tooltip title={blocked ? t("gdpr.approve_blocked_tooltip") : ""}>
                <Button
                  type="primary"
                  icon={<CheckOutlined />}
                  disabled={blocked}
                  onClick={() => setApproveTarget(row)}
                >
                  {t("gdpr.approve")}
                </Button>
              </Tooltip>
              <Button
                danger
                icon={<CloseOutlined />}
                onClick={() => onRejectRequested(row)}
              >
                {t("gdpr.reject")}
              </Button>
            </Space>
          );
        },
      },
    ],
    [t, formatDateTime, onRejectRequested],
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

      <ReadOnlyReportTable<AdminPendingDeletion>
        columns={columns}
        dataSource={pending}
        rowKey="id"
        pagination={false}
        loading={isFetching}
        emptyText={t("gdpr.no_pending")}
      />

      <ApproveDeletionModal
        request={approveTarget}
        approving={approving}
        onApprove={(row) => approveMutate({ requestId: row.id })}
        onCancel={() => setApproveTarget(null)}
      />
    </div>
  );
}
