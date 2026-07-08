import {
  DeleteOutlined,
  DownloadOutlined,
  SafetyOutlined,
} from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Divider, Space, Typography } from "antd";
import { useTranslation } from "react-i18next";
import { downloadBlob } from "@shared/utils";
import {
  getCommissioningMyCustomerDataRetrieveQueryKey,
  getCommissioningMyMemberDataRetrieveQueryKey,
} from "@shared/api/generated/commissioning/commissioning";
import {
  useGdprMyDataRetrieve,
  useGdprMyDeletionStatusRetrieve,
} from "@shared/api/generated/gdpr/gdpr";
import { useRoles } from "@shared/auth/useRoles";
import ConsentsSection from "./ConsentsSection";
import CustomerSection from "./CustomerSection";
import MemberSection from "./MemberSection";

const { Title, Paragraph } = Typography;

/**
 * "Meine Daten" tab content — role-aware editable surface.
 *
 *  * Member (incl. staff+member combo) → {@link MemberSection}
 *  * Customer-only → {@link CustomerSection}
 *  * Staff-only / no profile → friendly placeholder
 *
 * Below the role-specific form, every user sees their consent history
 * ({@link ConsentsSection}) and the GDPR footer with JSON-Export and
 * the deletion-request entry point.
 *
 * Sources of data (intentionally kept separate from the SAR bundle):
 *  * ``commissioning/my_member_data/`` and
 *    ``commissioning/my_customer_data/`` — the editable surface.
 *  * ``gdpr/my_data/`` — the comprehensive SAR bundle, used here only
 *    for the consents read-out and as the payload for "Export as JSON".
 */
export type MyDataTabProps = {
  onRequestDeletion: () => void;
};

export default function MyDataTab({ onRequestDeletion }: MyDataTabProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { member, customer, isStaff } = useRoles();

  // ``isStaff`` users who are ALSO members still get the member form
  // (their member identity is what's editable here). Staff-only users
  // have no editable self-profile.
  const showMember = member;
  const showCustomer = !showMember && customer;

  return (
    <Space
      direction="vertical"
      className="w-full"
      size="large"
    >
      {showMember ? (
        <MemberSection
          onSaved={() => {
            queryClient.invalidateQueries({
              queryKey: getCommissioningMyMemberDataRetrieveQueryKey(),
            });
          }}
        />
      ) : showCustomer ? (
        <CustomerSection
          onSaved={() => {
            queryClient.invalidateQueries({
              queryKey: getCommissioningMyCustomerDataRetrieveQueryKey(),
            });
          }}
        />
      ) : isStaff ? (
        <Paragraph type="secondary">
          {t("profile.no_editable_profile_staff")}
        </Paragraph>
      ) : (
        <Paragraph type="secondary">
          {t("profile.no_editable_profile")}
        </Paragraph>
      )}

      <ConsentsSection />
      <Divider />
      <Title level={5} style={{ marginBottom: 0 }}>
        {t("gdpr.data_protection")}
      </Title>
      <Alert
        message={t("gdpr.info_title")}
        description={t("gdpr.info_description")}
        type="info"
        showIcon
        icon={<SafetyOutlined />}
      />

      <AdvancedRightsFooter onRequestDeletion={onRequestDeletion} />
    </Space>
  );
}

function AdvancedRightsFooter({
  onRequestDeletion,
}: {
  onRequestDeletion: () => void;
}) {
  const { t } = useTranslation();
  // Staff (office / admin / any internal role) must NOT self-request account
  // deletion: an accidental click would lock them out of their own tenant
  // mid-shift. They ask the administration directly instead.
  const { isStaff } = useRoles();
  const { data: sar } = useGdprMyDataRetrieve();
  // Latest deletion-request status for THIS user. Surfaces above the
  // Request-Deletion button so a previously rejected request — and
  // the office's reason — is the first thing the user sees, instead
  // of silently re-submitting and waiting for a second rejection.
  const { data: deletionStatus } = useGdprMyDeletionStatusRetrieve();

  const handleExport = () => {
    if (!sar) return;
    const blob = new Blob([JSON.stringify(sar, null, 2)], {
      type: "application/json",
    });
    downloadBlob(blob, "my-personal-data.json");
  };

  const status = deletionStatus as
    | {
        state: string | null;
        requested_at: string | null;
        admin_confirmed_at: string | null;
        admin_rejection_reason: string | null;
      }
    | undefined;

  const renderStatusBanner = () => {
    if (!status || !status.state) return null;
    const fmt = (iso: string | null) =>
      iso ? new Date(iso).toLocaleString("de-DE") : "";
    switch (status.state) {
      case "pending_email":
        return (
          <Alert
            type="info"
            showIcon
            message={t("gdpr.status_pending_email")}
          />
        );
      case "pending_admin":
        return (
          <Alert
            type="info"
            showIcon
            message={t("gdpr.status_pending_admin")}
            description={t(
              "gdpr.status_pending_admin_detail",
              { date: fmt(status.requested_at) },
            )}
          />
        );
      case "rejected":
        return (
          <Alert
            type="warning"
            showIcon
            message={t("gdpr.status_rejected")}
            description={
              <>
                <div>
                  <strong>{t("gdpr.status_rejected_reason")}:</strong>{" "}
                  {status.admin_rejection_reason ||
                    t("gdpr.status_no_reason")}
                </div>
                {status.admin_confirmed_at && (
                  <div style={{ marginTop: 4, fontSize: 12, color: "var(--color-text-muted)" }}>
                    {t("gdpr.status_rejected_at", {
                      date: fmt(status.admin_confirmed_at),
                    })}
                  </div>
                )}
              </>
            }
          />
        );
      default:
        return null;
    }
  };

  return (
    <Space direction="vertical" size="middle" className="w-full">
      {renderStatusBanner()}
      <Space wrap>
        <Button size="small" icon={<DownloadOutlined />} onClick={handleExport}>
          {t("gdpr.export_json")}
        </Button>
        <Button
          size="small"
          danger
          icon={<DeleteOutlined />}
          onClick={onRequestDeletion}
          disabled={isStaff}
        >
          {t("gdpr.request_deletion")}
        </Button>
      </Space>
      {isStaff && (
        <Typography.Text type="secondary">
          {t("gdpr.deletion_staff_hint")}
        </Typography.Text>
      )}
    </Space>
  );
}
