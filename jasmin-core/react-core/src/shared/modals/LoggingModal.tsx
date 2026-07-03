import type { FC, ReactNode } from "react";
import { Modal, Descriptions, Tag } from "antd";
import ModalCloseFooter from "./ModalCloseFooter";
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  EditOutlined,
  MailOutlined,
  DollarOutlined,
  StopOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";
import { useDateFormat, useTimeFormat } from "@hooks/index";

interface LoggingRecord {
  created_at?: string | null;
  created_by_name?: string | null;
  updated_at?: string | null;
  updated_by_name?: string | null;
  cancelled_at?: string | null;
  cancelled_by_name?: string | null;
  cancelled_effective_at?: string | null;
  cancellation_reason?: string | null;
  admin_confirmed_at?: string | null;
  admin_confirmed_by_name?: string | null;
  admin_rejected_at?: string | null;
  admin_rejection_reason?: string | null;
  expires_at?: string | null;
  accepted_at?: string | null;
  invited_by_name?: string | null;
  paid_at?: string | null;
  [key: string]: unknown;
}

interface LoggingModalProps {
  isOpen: boolean;
  onClose: () => void;
  record: LoggingRecord | null;
  title?: string;
}

const LoggingModal: FC<LoggingModalProps> = ({
  isOpen,
  onClose,
  record,
  title,
}) => {
  const { t } = useTranslation();
  const { dateFormat } = useDateFormat() as { dateFormat: string };
  const { formatDateTime } = useTimeFormat();

  if (!record) return null;

  const formatDate = (value: string | null | undefined) => {
    if (!value) return null;
    return dayjs(value).format(dateFormat);
  };

  const entries: {
    label: string;
    date: string | null | undefined;
    by?: string | null;
    icon: ReactNode;
    color: string;
    extra?: string | null;
  }[] = [
    {
      label: t("logging.created"),
      date: record.created_at,
      by: record.created_by_name,
      icon: <CheckCircleOutlined />,
      color: "green",
    },
    {
      label: t("logging.updated"),
      date: record.updated_at,
      by: record.updated_by_name,
      icon: <EditOutlined />,
      color: "blue",
    },
    {
      label: t("logging.invited"),
      date: record.invited_by_name ? record.created_at : undefined,
      by: record.invited_by_name,
      icon: <MailOutlined />,
      color: "purple",
    },
    {
      label: t("logging.accepted"),
      date: record.accepted_at,
      icon: <CheckCircleOutlined />,
      color: "cyan",
    },
    {
      // Office admission. ``reject()`` stores the acting admin in
      // ``admin_confirmed_by``, so ``admin_confirmed_by_name`` is the rejecter
      // on a rejected row and the approver on an approved one.
      label: t("logging.admin_confirmed"),
      date: record.admin_confirmed_at,
      by: record.admin_confirmed_by_name,
      icon: <CheckCircleOutlined />,
      color: "green",
    },
    {
      label: t("logging.admin_rejected"),
      date: record.admin_rejected_at,
      by: record.admin_confirmed_by_name,
      icon: <CloseCircleOutlined />,
      color: "red",
      extra: record.admin_rejection_reason
        ? `${t("logging.reason")}: ${record.admin_rejection_reason}`
        : undefined,
    },
    {
      label: t("logging.paid"),
      date: record.paid_at,
      icon: <DollarOutlined />,
      color: "gold",
    },
    {
      label: t("logging.cancelled"),
      date: record.cancelled_at,
      by: record.cancelled_by_name,
      icon: <StopOutlined />,
      color: "red",
      // Stitch "effective on …" and "reason: …" into one extra line so
      // both bits of context show up next to the cancellation event.
      // The reason is sourced from the SubscriptionGroup server-side
      // (see ``SubscriptionSerializer.cancellation_reason``).
      extra:
        [
          record.cancelled_effective_at
            ? `${t("logging.effective_at")}: ${formatDate(record.cancelled_effective_at)}`
            : null,
          record.cancellation_reason
            ? `${t("logging.reason")}: ${record.cancellation_reason}`
            : null,
        ]
          .filter(Boolean)
          .join(" — ") || undefined,
    },
    {
      label: t("logging.expires"),
      date: record.expires_at,
      icon: <ClockCircleOutlined />,
      color: "orange",
    },
  ];

  const visibleEntries = entries.filter((e) => e.date);

  return (
    <Modal
      title={title || t("logging.title")}
      open={isOpen}
      onCancel={onClose}
      footer={[
        <ModalCloseFooter key="close" onClose={onClose} />,
      ]}
      width={480}
    >
      {visibleEntries.length === 0 ? (
 <span className="text-muted">
          {t("logging.no_data")}
        </span>
      ) : (
        <Descriptions column={1} size="small" bordered>
          {visibleEntries.map((entry) => (
            <Descriptions.Item
              key={entry.label}
              label={
                <Tag icon={entry.icon} color={entry.color}>
                  {entry.label}
                </Tag>
              }
            >
              <div>{formatDateTime(entry.date)}</div>
              {entry.by && (
                <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>{entry.by}</div>
              )}
              {entry.extra && (
                <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>{entry.extra}</div>
              )}
            </Descriptions.Item>
          ))}
        </Descriptions>
      )}
    </Modal>
  );
};

export default LoggingModal;
