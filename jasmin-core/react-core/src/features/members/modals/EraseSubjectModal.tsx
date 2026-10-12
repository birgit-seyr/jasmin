import { useQueryClient } from "@tanstack/react-query";
import { Alert, Modal, Select, Typography } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  getGdprAdminDecidedDeletionsListQueryKey,
  getGdprAdminPendingDeletionsRetrieveQueryKey,
  useGdprAdminMembersEraseCreate,
  useGdprAdminResellersEraseCreate,
} from "@shared/api/generated/gdpr/gdpr";
import { ChannelEnum } from "@shared/api/generated/models";
import { notify } from "@shared/utils";
import {
  getErrorCode,
  getErrorDetails,
  getErrorMessage,
} from "@shared/utils/apiError";

import type { GdprSubject } from "../components/GdprSubjectActions";

const { Paragraph, Text } = Typography;

interface EraseSubjectModalProps {
  open: boolean;
  subject: GdprSubject;
  onClose: () => void;
  onErased?: () => void;
}

/**
 * Erase a member's or reseller's personal data on their request, recording
 * how they asked. When obligations the law makes us keep the data for still
 * block it, the modal lists them: the request then waits in the deletion
 * inbox until they are settled.
 */
export default function EraseSubjectModal({
  open,
  subject,
  onClose,
  onErased,
}: EraseSubjectModalProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [channel, setChannel] = useState<ChannelEnum | undefined>();
  const [blockers, setBlockers] = useState<string[] | null>(null);
  const eraseMember = useGdprAdminMembersEraseCreate({
    mutation: { meta: { silent: true } },
  });
  const eraseReseller = useGdprAdminResellersEraseCreate({
    mutation: { meta: { silent: true } },
  });
  const erasing = eraseMember.isPending || eraseReseller.isPending;

  const close = () => {
    setChannel(undefined);
    setBlockers(null);
    onClose();
  };

  const refreshInbox = () => {
    queryClient.invalidateQueries({
      queryKey: getGdprAdminPendingDeletionsRetrieveQueryKey(),
    });
    queryClient.invalidateQueries({
      queryKey: getGdprAdminDecidedDeletionsListQueryKey(),
    });
  };

  const handleErase = async () => {
    if (!channel) return;
    const data = { channel };
    try {
      if (subject.kind === "member") {
        await eraseMember.mutateAsync({ memberId: subject.id, data });
      } else {
        await eraseReseller.mutateAsync({ resellerId: subject.id, data });
      }
      notify.success(t("gdpr.office_actions.erased"));
      refreshInbox();
      onErased?.();
      close();
    } catch (error) {
      const reasons = getErrorDetails(error)?.reasons;
      if (getErrorCode(error) === "gdpr.retention_active" && Array.isArray(reasons)) {
        // The request was filed and now waits in the inbox.
        refreshInbox();
        setBlockers(reasons.map(String));
      } else {
        notify.error(getErrorMessage(error));
      }
    }
  };

  return (
    <Modal
      open={open}
      title={t("gdpr.office_actions.erase_title")}
      onCancel={close}
      onOk={blockers ? close : handleErase}
      okText={blockers ? t("common.close") : t("gdpr.office_actions.erase_confirm")}
      okButtonProps={{ danger: !blockers, disabled: !blockers && !channel }}
      cancelButtonProps={{ hidden: !!blockers }}
      confirmLoading={erasing}
      destroyOnHidden
    >
      {blockers ? (
        <Alert
          type="warning"
          showIcon
          message={t("gdpr.office_actions.blocked_title")}
          description={
            <>
              <Paragraph>{t("gdpr.office_actions.blocked_intro")}</Paragraph>
              <ul>
                {blockers.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            </>
          }
        />
      ) : (
        <>
          <Paragraph>{t("gdpr.office_actions.erase_intro")}</Paragraph>
          <label htmlFor="erase-subject-channel">
            <Text strong>{t("gdpr.office_actions.channel_label")}</Text>
          </label>
          <Select<ChannelEnum>
            id="erase-subject-channel"
            className="w-full"
            value={channel}
            onChange={setChannel}
            placeholder={t("gdpr.office_actions.channel_placeholder")}
            options={Object.values(ChannelEnum).map((value) => ({
              value,
              label: t(`gdpr.channel.${value}`),
            }))}
          />
        </>
      )}
    </Modal>
  );
}
