import { CloseCircleOutlined } from "@ant-design/icons";
import { Alert, Input, Modal, Space, Typography } from "antd";
import type { FC, ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { ModalCancelSaveFooter } from "@shared/modals/shared";

const { Title, Paragraph } = Typography;

export interface AdminRejectionModalProps {
  isOpen: boolean;
  onClose: () => void;
  reason: string;
  onReasonChange: (value: string) => void;
  onReject: () => void;
  loading?: boolean;
  /** Modal title. */
  title: string;
  /** Heading line (the entity name) shown above the warning. */
  heading: ReactNode;
  /** Warning Alert copy. */
  warningTitle: string;
  warningBody: string;
  /** Reason textarea placeholder. */
  reasonPlaceholder: string;
}

/**
 * Generic "admin rejects an application with a reason" modal — the shared
 * structure behind the subscription (Abo) and member-application reject
 * flows, mirroring the AdminConfirmation side. The entity-specific copy
 * (title, heading, warning, placeholder) is supplied by the thin
 * per-feature wrappers (``RejectAboModal`` / ``RejectMemberModal``); the
 * Modal / footer / Alert / reason-textarea layout lives here once so
 * future changes (char limit, accessibility, validation) are made in a
 * single place.
 */
export const AdminRejectionModal: FC<AdminRejectionModalProps> = ({
  isOpen,
  onClose,
  reason,
  onReasonChange,
  onReject,
  loading = false,
  title,
  heading,
  warningTitle,
  warningBody,
  reasonPlaceholder,
}) => {
  const { t } = useTranslation();

  return (
    <Modal
      title={title}
      open={isOpen}
      onCancel={onClose}
      footer={
        <ModalCancelSaveFooter
          onCancel={onClose}
          onPrimary={onReject}
          loading={loading}
          primaryDanger
          primaryIcon={<CloseCircleOutlined />}
          primaryLabel={t("members.reject_member")}
        />
      }
      width={560}
      destroyOnHidden
    >
      <Space direction="vertical" size="middle" className="w-full">
        <Title level={5} style={{ margin: 0 }}>
          {heading}
        </Title>

        <Alert
          type="warning"
          showIcon
          message={warningTitle}
          description={warningBody}
        />

        <div>
          <Paragraph style={{ marginBottom: 4 }}>
            {t("members.reject_reason_label")}
          </Paragraph>
          <Input.TextArea
            value={reason}
            onChange={(e) => onReasonChange(e.target.value)}
            rows={4}
            maxLength={1000}
            showCount
            placeholder={reasonPlaceholder}
            disabled={loading}
          />
        </div>
      </Space>
    </Modal>
  );
};

export default AdminRejectionModal;
