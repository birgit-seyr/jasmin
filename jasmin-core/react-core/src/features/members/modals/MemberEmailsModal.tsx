import type { FC } from "react";
import { useMemo } from "react";
import { Modal, Table, Tag, Tooltip } from "antd";
import ModalCloseFooter from "@shared/modals/ModalCloseFooter";
import type { ColumnsType } from "antd/es/table";
import { useTranslation } from "react-i18next";
import { useCommissioningMembersEmailsList } from "@shared/api/generated/commissioning/commissioning";
import type { MemberEmailLog } from "@shared/api/generated/models";
import { useTimeFormat } from "@hooks/index";
import { getEmailStatusColor } from "@shared/utils/emailStatusColors";

interface MemberEmailsModalProps {
  isOpen: boolean;
  onClose: () => void;
  memberId: string | null;
  memberName?: string;
}

const MemberEmailsModal: FC<MemberEmailsModalProps> = ({
  isOpen,
  onClose,
  memberId,
  memberName,
}) => {
  const { t } = useTranslation();
  const { formatDateTime } = useTimeFormat();

  // Skip the query until the modal opens. Once the office user opens
  // the modal we keep the result in cache so re-opens are instant.
  // Signature is ``(id, params, {query})``: positional 2 is reserved
  // for orval URL params (none here), positional 3 is the TanStack
  // Query options.
  const { data, isLoading } = useCommissioningMembersEmailsList(
    memberId ?? "",
    undefined,
    {
      query: {
        enabled: !!memberId && isOpen,
      },
    },
  );

  const rows = useMemo<MemberEmailLog[]>(() => data ?? [], [data]);

  const columns = useMemo<ColumnsType<MemberEmailLog>>(
    () => [
      {
        title: t("logging.created"),
        dataIndex: "created_at",
        key: "created_at",
        width: "11em",
        sorter: (a, b) => a.created_at.localeCompare(b.created_at),
        defaultSortOrder: "descend",
        render: (value: string) => formatDateTime(value),
      },
      {
        title: t("email_matrix.purpose"),
        dataIndex: "purpose",
        key: "purpose",
        sorter: (a, b) => a.purpose.localeCompare(b.purpose),
        render: (value: string) => (
          <Tooltip title={value}>
            <span>{t(`email_matrix.${value}`)}</span>
          </Tooltip>
        ),
      },
      {
        title: t("email_matrix.subject"),
        dataIndex: "subject",
        key: "subject",
        ellipsis: true,
      },
      {
        title: t("email_matrix.status_col"),
        dataIndex: "status",
        key: "status",
        width: "8em",
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
        render: (value: string | null) => (value ? formatDateTime(value) : "—"),
      },
      {
        title: t("email_matrix.delivered_at"),
        dataIndex: "delivered_at",
        key: "delivered_at",
        width: "11em",
        render: (value: string | null) => (value ? formatDateTime(value) : "—"),
      },
    ],
    [t, formatDateTime],
  );

  return (
    <Modal
      title={
        memberName
          ? `${t("members.sent_emails")} — ${memberName}`
          : t("members.sent_emails")
      }
      open={isOpen}
      onCancel={onClose}
      footer={[<ModalCloseFooter key="close" onClose={onClose} />]}
      width={1000}
    >
      <Table<MemberEmailLog>
        columns={columns}
        dataSource={rows}
        rowKey="id"
        loading={isLoading}
        pagination={{ pageSize: 20 }}
        className="custom-jasmin-table"
        size="small"
        locale={{
          emptyText: t("members.no_emails_sent"),
        }}
      />
    </Modal>
  );
};

export default MemberEmailsModal;
