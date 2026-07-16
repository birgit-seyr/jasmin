import { useQueryClient } from "@tanstack/react-query";
import { Button, Input, Space } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  getSupportTicketsListQueryKey,
  getSupportTicketsRetrieveQueryKey,
  useSupportTicketsReplyCreate,
} from "@shared/api/generated/support/support";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";

/** Textarea + Send for posting a staff reply to a ticket thread. */
export default function ReplyComposer({ ticketId }: { ticketId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [body, setBody] = useState("");

  const replyMutation = useSupportTicketsReplyCreate({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({
          queryKey: getSupportTicketsRetrieveQueryKey(ticketId),
        });
        void queryClient.invalidateQueries({
          queryKey: getSupportTicketsListQueryKey(),
        });
        setBody("");
        notify.success(t("support.thread.reply_sent"));
      },
      onError: (err) => notify.error(getErrorMessage(err)),
    },
  });

  const send = () => {
    const trimmed = body.trim();
    if (!trimmed) return;
    replyMutation.mutate({ id: ticketId, data: { body: trimmed } });
  };

  return (
    <Space.Compact style={{ width: "100%", marginTop: 12 }}>
      <Input.TextArea
        value={body}
        onChange={(event) => setBody(event.target.value)}
        placeholder={t("support.thread.reply_placeholder")}
        aria-label={t("support.thread.reply_placeholder")}
        autoSize={{ minRows: 2, maxRows: 6 }}
      />
      <Button
        type="primary"
        onClick={send}
        loading={replyMutation.isPending}
        disabled={!body.trim()}
      >
        {t("support.thread.reply_send")}
      </Button>
    </Space.Compact>
  );
}
