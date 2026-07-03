import { Descriptions, Modal, Tag } from "antd";
import type { FC } from "react";
import { useTranslation } from "react-i18next";
import {
  adminConfirmationAuditItems,
  type AdminConfirmableRecord,
  getAdminConfirmationStatus,
  adminConfirmationFooter,
} from "@shared/modals/shared";
import { useCurrency, useTimeFormat } from "@hooks/index";

/** A coop-share row as far as the admin-confirmation modal cares. */
export interface CoopShareConfirmRecord extends AdminConfirmableRecord {
  id?: string;
  amount_of_coop_shares?: string;
  value_one_coop_share?: number;
  member_string?: string;
}

interface AdminConfirmationModalCoopSharesProps {
  isOpen: boolean;
  onClose: () => void;
  coopShare: CoopShareConfirmRecord | null;
  onConfirm?: () => void;
  loading?: boolean;
}

/**
 * Admin-confirmation modal for a single cooperative share — the same shape as
 * the members / abos confirmation modals (status banner + audit line of who
 * confirmed it and when), reusing the shared admin-confirmation toolkit.
 */
export const AdminConfirmationModalCoopShares: FC<
  AdminConfirmationModalCoopSharesProps
> = ({ isOpen, onClose, coopShare, onConfirm, loading = false }) => {
  const { t } = useTranslation();
  const { formatDateTime } = useTimeFormat();
  const { currencySymbol } = useCurrency();

  if (!coopShare) {
    return null;
  }

  const status = getAdminConfirmationStatus(coopShare, t);
  const amount = Number(coopShare.amount_of_coop_shares ?? 0);
  const valueOne = Number(coopShare.value_one_coop_share ?? 0);

  return (
    <Modal
      title={t("members.admin_confirmation_title")}
      open={isOpen}
      onCancel={onClose}
      footer={adminConfirmationFooter({
        isTerminal: coopShare.admin_confirmed,
        onClose,
        onConfirm,
        confirmLabel: t("members.confirm_coop_share"),
        cancelLabel: t("common.cancel"),
        loading,
      })}
      width={520}
      destroyOnHidden
    >
      <Descriptions
        column={1}
        bordered
        size="small"
        style={{ marginTop: 16, marginBottom: 12 }}
      >
        {coopShare.member_string && (
          <Descriptions.Item label={t("members.member")}>
            {coopShare.member_string}
          </Descriptions.Item>
        )}
        <Descriptions.Item label={t("members.amount_of_coop_shares")}>
          {amount}
        </Descriptions.Item>
        {valueOne > 0 && (
          <Descriptions.Item label={t("members.coop_shares_total_value")}>
            {currencySymbol}
            {(amount * valueOne).toFixed(2)}
          </Descriptions.Item>
        )}
        <Descriptions.Item label={t("members.current_status")}>
          {status && (
            <Tag color={status.color} icon={status.icon}>
              {status.text}
            </Tag>
          )}
        </Descriptions.Item>
        {adminConfirmationAuditItems(coopShare, t, formatDateTime)}
      </Descriptions>
    </Modal>
  );
};

export default AdminConfirmationModalCoopShares;
