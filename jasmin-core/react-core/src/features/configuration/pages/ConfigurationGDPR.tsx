import { useQueryClient } from "@tanstack/react-query";
import { Alert, Input, Modal, Space, Typography } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  getGdprAdminDecidedDeletionsListQueryKey,
  getGdprAdminPendingDeletionsRetrieveQueryKey,
  useGdprAdminRejectDeletionCreate,
} from "@shared/api/generated/gdpr/gdpr";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import type { AdminPendingDeletion } from "@shared/api/generated/models";
import DecidedDeletionsCard from "@features/configuration/components/DecidedDeletionsCard";
import PendingDeletionsCard from "@features/configuration/components/PendingDeletionsCard";
import PrivacyPolicyEditorCard from "@features/configuration/components/PrivacyPolicyEditorCard";
import VVTControllerFieldsCard from "@features/configuration/components/VVTControllerFieldsCard";
import VVTExportCard from "@features/configuration/components/VVTExportCard";

const { Paragraph } = Typography;

/**
 * Admin-only GDPR page. Top-down:
 *  - mandatory-approval policy banner
 *  - pending-request inbox (action)
 *  - decided-request history (audit-trail + reasons)
 *
 * Reject modal is hoisted here so the same dialog could later be
 * triggered from other surfaces (notifications, member detail page,
 * …) without duplicating it per card.
 */
export default function ConfigurationGDPR() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [rejectTarget, setRejectTarget] = useState<AdminPendingDeletion | null>(
    null,
  );
  const [rejectReason, setRejectReason] = useState("");

  const closeRejectModal = () => {
    setRejectTarget(null);
    setRejectReason("");
  };

  const { mutate: rejectMutate, isPending: isRejecting } =
    useGdprAdminRejectDeletionCreate({
      mutation: {
        onSuccess: () => {
          notify.success(t("gdpr.rejected"));
          // Pending list shrinks; decided list gains a new row.
          queryClient.invalidateQueries({
            queryKey: getGdprAdminPendingDeletionsRetrieveQueryKey(),
          });
          queryClient.invalidateQueries({
            queryKey: getGdprAdminDecidedDeletionsListQueryKey(),
          });
          closeRejectModal();
        },
        onError: (error) => {
          notify.error(getErrorMessage(error, "Failed to reject"));
        },
      },
    });

  const handleRejectConfirm = () => {
    if (!rejectTarget || !rejectReason.trim()) return;
    rejectMutate({
      requestId: rejectTarget.id,
      data: { reason: rejectReason.trim() } as never,
    });
  };

  return (
    <>
      <h1>{t("gdpr.title")}</h1>
      <Space direction="vertical" size="middle" className="w-full">
        <PrivacyPolicyEditorCard />
        <PendingDeletionsCard onRejectRequested={setRejectTarget} />
        <DecidedDeletionsCard />
        {/* Art. 30 VVT: the controller-identity fields (legal form, DPO,
            data-protection contact, supervisory authority) feed the export
            below, then the export itself. */}
        <VVTControllerFieldsCard />
        <VVTExportCard />
      </Space>

      <Modal
        title={t("gdpr.reject_title")}
        open={rejectTarget !== null}
        onCancel={closeRejectModal}
        onOk={handleRejectConfirm}
        okButtonProps={{
          danger: true,
          disabled: !rejectReason.trim(),
          loading: isRejecting,
        }}
        okText={t("gdpr.reject")}
        cancelText={t("common.cancel")}
      >
        <Paragraph>
          {t("gdpr.reject_reason_prompt")}
        </Paragraph>
        <Input.TextArea
          rows={4}
          value={rejectReason}
          onChange={(e) => setRejectReason(e.target.value)}
          placeholder={t("gdpr.reject_reason_placeholder")}
        />
      </Modal>
    </>
  );
}
