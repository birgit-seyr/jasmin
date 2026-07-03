import { Button, Descriptions, Modal, Space, Tag } from "antd";
import type { FC } from "react";
import { useTranslation } from "react-i18next";
import { useDateFormat } from "@hooks/index";
import type {
  AccountStatus,
  LinkedUserInfo,
} from "@hooks/modals/useUserInfoModal";

interface UserRecord {
  linked_user_info?: LinkedUserInfo | null;
  company_name?: string;
  first_name?: string;
  last_name?: string;
  email?: string;
  last_login?: string;
  [key: string]: unknown;
}

interface UserInfoModalProps {
  isOpen: boolean;
  onClose: () => void;
  record: UserRecord | null;
  /** Send a fresh invitation (no existing user account). */
  onSendInvitation?: (record: UserRecord) => void;
  /** Resend an invitation that's still pending. */
  onResendInvitation?: (record: UserRecord) => void;
  /** Activate a deactivated user. */
  onActivateUser?: (record: UserRecord) => void;
  /** Deactivate an active user. */
  onDeactivateUser?: (record: UserRecord) => void;
}

const STATUS_TAG_COLOR: Record<AccountStatus | "no_user", string> = {
  active: "green",
  pending_approval: "gold",
  pending_invitation: "blue",
  inactive: "default",
  no_user: "red",
};

const UserInfoModal: FC<UserInfoModalProps> = ({
  isOpen,
  onClose,
  record,
  onSendInvitation,
  onResendInvitation,
  onActivateUser,
  onDeactivateUser,
}) => {
  const { t } = useTranslation();
  const { formatDateWithFallback } = useDateFormat();

  if (!record) return null;

  const info = record.linked_user_info;

  const accountStatus: AccountStatus | "no_user" =
    info?.account_status ?? "no_user";

  const isInvitationExpired = !!info?.is_invitation_expired;
  const statusKey =
    accountStatus === "no_user" ? "status_no_user" : `status_${accountStatus}`;
  const descriptionKey = `${statusKey}_description`;

  // ---- Display fields ---------------------------------------------------
  const firstName = info?.first_name || record.first_name || "";
  const lastName = info?.last_name || record.last_name || "";
  const email = info?.email || record.email || "";
  const lastLogin = info?.last_login || record.last_login || null;
  const activatedAt = info?.activated_at || null;
  const inactivatedAt = info?.inactivated_at || null;
  const invitationExpiresAt = info?.invitation_expires_at || null;

  const handleSendInvitation = () => onSendInvitation?.(record);
  const handleResendInvitation = () => onResendInvitation?.(record);
  const handleActivate = () => onActivateUser?.(record);
  const handleDeactivate = () => onDeactivateUser?.(record);
  return (
    <Modal
      title={t("members.user_info_modal_title")}
      open={isOpen}
      onCancel={onClose}
      footer={null}
      width={700}
    >
      <Descriptions column={1} bordered>
        {record.company_name ? (
          <Descriptions.Item label={t("resellers.company_name")}>
            {record.company_name}
          </Descriptions.Item>
        ) : null}
        <Descriptions.Item label={t("resellers.first_name")}>
          {firstName || "—"}
        </Descriptions.Item>
        <Descriptions.Item label={t("resellers.last_name")}>
          {lastName || "—"}
        </Descriptions.Item>
        <Descriptions.Item label={t("resellers.email")}>
          {email || "—"}
        </Descriptions.Item>
        <Descriptions.Item label={t("members.user_status")}>
          <Tag color={STATUS_TAG_COLOR[accountStatus]}>
            {t(`users.${statusKey}`)}
          </Tag>
          <div
            style={{
              marginTop: 8,
              fontSize: "12px",
              color: "var(--color-text-secondary)",
            }}
          >
            {t(`users.${descriptionKey}`)}
          </div>
        </Descriptions.Item>
        {accountStatus === "pending_invitation" && invitationExpiresAt ? (
          <Descriptions.Item label={t("users.invitation_expires")}>
            {formatDateWithFallback(invitationExpiresAt)}
            {isInvitationExpired && (
              <Tag color="red" style={{ marginLeft: 8 }}>
                {t("users.invitation_expired")}
              </Tag>
            )}
          </Descriptions.Item>
        ) : null}
        {activatedAt ? (
          <Descriptions.Item label={t("users.active_since")}>
            {formatDateWithFallback(activatedAt)}
          </Descriptions.Item>
        ) : null}
        {accountStatus === "inactive" && inactivatedAt ? (
          <Descriptions.Item label={t("users.inactivated_at")}>
            {formatDateWithFallback(inactivatedAt)}
          </Descriptions.Item>
        ) : null}
        {accountStatus === "active" && lastLogin ? (
          <Descriptions.Item label={t("users.last_login")}>
            {formatDateWithFallback(lastLogin)}
          </Descriptions.Item>
        ) : null}
        {accountStatus === "active" && !lastLogin ? (
          <Descriptions.Item label={t("users.last_login")}>
            <span
              style={{
                color: "var(--color-text-tertiary)",
                fontStyle: "italic",
              }}
            >
              {t("users.never")}
            </span>
          </Descriptions.Item>
        ) : null}
      </Descriptions>

      <div style={{ marginTop: 16, textAlign: "right" }}>
        <Space>
          {accountStatus === "no_user" && onSendInvitation && (
            <Button type="primary" onClick={handleSendInvitation}>
              {t("users.send_invitation")}
            </Button>
          )}
          {accountStatus === "pending_invitation" && onResendInvitation && (
            <Button
              type={isInvitationExpired ? "default" : "primary"}
              disabled={isInvitationExpired}
              onClick={handleResendInvitation}
            >
              {t("users.resend_invitation")}
            </Button>
          )}
          {accountStatus === "pending_invitation" &&
            isInvitationExpired &&
            onSendInvitation && (
              <Button type="primary" onClick={handleSendInvitation}>
                {t("users.send_new_invitation")}
              </Button>
            )}
          {accountStatus === "active" && onDeactivateUser && (
            <Button danger onClick={handleDeactivate}>
              {t("users.deactivate")}
            </Button>
          )}
          {accountStatus === "inactive" && onActivateUser && (
            <Button type="primary" onClick={handleActivate}>
              {t("users.activate")}
            </Button>
          )}
        </Space>
      </div>
    </Modal>
  );
};

export default UserInfoModal;
