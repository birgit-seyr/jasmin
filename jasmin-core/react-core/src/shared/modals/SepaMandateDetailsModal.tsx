import {
  CheckCircleOutlined,
  CloseCircleOutlined,
} from "@ant-design/icons";
import { Descriptions, Modal, Tag, Typography } from "antd";
import type { FC } from "react";
import { useTranslation } from "react-i18next";
import type { SepaMandateStatus } from "@shared/api/generated/models";
import { useDateFormat } from "@hooks/configuration/useDateFormat";
import { isSepaMandateActiveForTerm } from "@shared/utils";

const { Text } = Typography;

interface SepaMandateDetailsModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** Resolved mandate status for the member (undefined = no billing profile). */
  status: SepaMandateStatus | undefined;
  /** Display name of the owning member, for the header row. */
  memberName?: string;
  /** The subscription's end date — drives the "active during this term" tag. */
  validUntil?: string | null;
}

/**
 * Read-only SEPA mandate details, opened from the Abos SEPA status square.
 * Reuses the same ``sepa.*`` labels + active/missing tag styling as the
 * admin-confirmation modal, and deliberately shows NO bank identifiers (the
 * ``mandate_status`` payload carries none).
 */
export const SepaMandateDetailsModal: FC<SepaMandateDetailsModalProps> = ({
  isOpen,
  onClose,
  status,
  memberName,
  validUntil,
}) => {
  const { t } = useTranslation();
  const { formatDate } = useDateFormat();

  const activeForTerm = isSepaMandateActiveForTerm(status, validUntil);

  return (
    <Modal
      title={t("sepa.mandate_status")}
      open={isOpen}
      onCancel={onClose}
      footer={null}
      width={520}
      destroyOnHidden
    >
      {!status ? (
        <Text type="secondary">{t("sepa.no_profile")}</Text>
      ) : (
        <Descriptions column={1} bordered size="small">
          {memberName && (
            <Descriptions.Item label={t("sepa.member")}>
              {memberName}
            </Descriptions.Item>
          )}
          <Descriptions.Item label={t("sepa.mandate_active_for_term")}>
            {activeForTerm ? (
              <Tag color="green" icon={<CheckCircleOutlined />}>
                {t("common.yes")}
              </Tag>
            ) : (
              <Tag color="red" icon={<CloseCircleOutlined />}>
                {t("common.no")}
              </Tag>
            )}
          </Descriptions.Item>
          <Descriptions.Item label={t("sepa.status")}>
            {status.has_active_sepa_mandate ? (
              <Tag color="green" icon={<CheckCircleOutlined />}>
                {t("sepa.mandate_active")}
              </Tag>
            ) : (
              <Tag color="red" icon={<CloseCircleOutlined />}>
                {t("sepa.mandate_missing")}
              </Tag>
            )}
          </Descriptions.Item>
          {status.sepa_mandate_reference && (
            <Descriptions.Item label={t("sepa.mandate_reference")}>
              {status.sepa_mandate_reference}
            </Descriptions.Item>
          )}
          {status.sepa_mandate_signed_at && (
            <Descriptions.Item label={t("sepa.signed_at")}>
              {formatDate(status.sepa_mandate_signed_at)}
            </Descriptions.Item>
          )}
          {status.sepa_mandate_paper_received_at && (
            <Descriptions.Item label={t("sepa.paper_received_at")}>
              {formatDate(status.sepa_mandate_paper_received_at)}
            </Descriptions.Item>
          )}
        </Descriptions>
      )}
    </Modal>
  );
};

export default SepaMandateDetailsModal;
