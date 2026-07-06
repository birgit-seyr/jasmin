import { CopyOutlined } from "@ant-design/icons";
import { Button, Flex, Input, Spin, Typography } from "antd";
import { useTranslation } from "react-i18next";
import type { SubscriptionMemberEmailsResponse } from "@shared/api/generated/models";
import { notify } from "@shared/utils";

const { Text } = Typography;

interface CopyableEmailListProps {
  data: SubscriptionMemberEmailsResponse | undefined;
  loading: boolean;
  /** Whether a filter is selected — otherwise we prompt the office to pick one. */
  enabled: boolean;
}

/**
 * A copyable e-mail distribution list: the recipient count, a read-only
 * ``;``-joined block of addresses, and a one-click copy button. Fed by the
 * ``subscription_member_emails`` endpoint on the AbosEmails page.
 */
export default function CopyableEmailList({
  data,
  loading,
  enabled,
}: CopyableEmailListProps) {
  const { t } = useTranslation();

  if (!enabled) {
    return (
      <Text type="secondary" style={{ display: "block" }}>
        {t("abos.emails_select_filter_hint")}
      </Text>
    );
  }

  if (loading) {
    return <Spin size="small" />;
  }

  const emails = (data?.members ?? []).map((m) => m.email);

  if (emails.length === 0) {
    return (
      <Text type="secondary" style={{ display: "block" }}>
        {t("abos.emails_no_recipients")}
      </Text>
    );
  }

  const joined = emails.join("; ");
  const copy = () => {
    navigator.clipboard.writeText(joined).then(
      () => notify.success(t("abos.emails_copied", { count: emails.length })),
      () => notify.error(t("common.error")),
    );
  };

  return (
    <div style={{ width: "100%" }}>
      <Flex align="center" gap="small" style={{ marginBottom: 8 }}>
        <Text strong>
          {t("abos.emails_recipients", { count: emails.length })}
        </Text>
        <Button size="small" icon={<CopyOutlined />} onClick={copy}>
          {t("abos.emails_copy")}
        </Button>
      </Flex>
      <Input.TextArea
        readOnly
        value={joined}
        autoSize={{ minRows: 2, maxRows: 8 }}
        onFocus={(e) => e.target.select()}
      />
    </div>
  );
}
