import { List, Tag, Typography } from "antd";
import { useTranslation } from "react-i18next";
import type { SupportTicketMessage } from "@shared/api/generated/models";
import { useDateFormat } from "@hooks/index";

const { Text, Paragraph } = Typography;

/** Read-only message thread (tenant side, AntD + i18n). The platform page has
 *  its own plain renderer — the two data sources differ and the platform app is
 *  deliberately AntD-free, so they are intentionally NOT shared. */
export default function TicketThread({
  messages,
}: {
  messages: readonly SupportTicketMessage[];
}) {
  const { t } = useTranslation();
  const { formatDate } = useDateFormat();

  if (!messages.length) {
    return <div className="text-muted">{t("support.thread.no_messages")}</div>;
  }

  return (
    <List
      className="support-thread"
      itemLayout="vertical"
      split={false}
      dataSource={messages.slice()}
      renderItem={(message) => (
        <List.Item key={message.id} className="support-thread-message">
          <div className="flex-between">
            <Text strong>
              {message.author_name ||
                t(`support.author.${message.author_kind}`)}
            </Text>
            <Tag color={message.author_kind === "super_admin" ? "blue" : "green"}>
              {t(`support.author.${message.author_kind}`)}
            </Tag>
          </div>
          <Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: 4 }}>
            {message.body}
          </Paragraph>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {message.created_at ? formatDate(message.created_at) : ""}
          </Text>
        </List.Item>
      )}
    />
  );
}
