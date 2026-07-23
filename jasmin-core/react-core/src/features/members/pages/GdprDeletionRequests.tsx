import { useQueryClient } from "@tanstack/react-query";
import { Input, Modal, Space, Typography } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  getGdprAdminDecidedDeletionsListQueryKey,
  getGdprAdminPendingDeletionsRetrieveQueryKey,
  useGdprAdminRejectDeletionCreate,
} from "@shared/api/generated/gdpr/gdpr";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import { ExplainerText } from "@shared/ui";
import type { AdminPendingDeletion } from "@shared/api/generated/models";
import DecidedDeletionsTable from "@features/members/components/DecidedDeletionsTable";
import PendingDeletionsTable from "@features/members/components/PendingDeletionsTable";

const { Paragraph } = Typography;

/**
 * Admin GDPR deletion-request queue (member offboarding): the pending-request
 * inbox + the decided-request history, with the reject-reason modal hoisted
 * here. Lives in the Members section — it's a member-lifecycle tool, not a
 * tenant setting. The privacy policy + Art. 30 VVT records stay on the
 * Configuration GDPR page (``ConfigurationGDPR``).
 */
export default function GdprDeletionRequests() {
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
      <h1>{t("members.dsgvo_deletion")}</h1>
      <Space direction="vertical" size="middle" className="w-full">
        <PendingDeletionsTable onRejectRequested={setRejectTarget} />
        <DecidedDeletionsTable />
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
        <Paragraph>{t("gdpr.reject_reason_prompt")}</Paragraph>
        <Input.TextArea
          rows={4}
          value={rejectReason}
          onChange={(e) => setRejectReason(e.target.value)}
          placeholder={t("gdpr.reject_reason_placeholder")}
        />
      </Modal>

      <ExplainerText title={t("common.info")}>
        {t("explainers.gdpr_deletion_requests")}
      </ExplainerText>
    </>
  );
}
