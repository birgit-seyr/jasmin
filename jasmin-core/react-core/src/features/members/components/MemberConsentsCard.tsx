import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  DownloadOutlined,
  StopOutlined,
} from "@ant-design/icons";
import { useTimeFormat } from "@hooks/index";
import {
  getCommissioningConsentsListQueryKey,
  getCommissioningMembersRetrieveQueryKey,
  useCommissioningConsentsList,
  useCommissioningConsentsRevokeCreate,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  ConsentDocumentSummary,
  ConsentRecord,
  ConsentRecordRevoke,
} from "@shared/api/generated/models";
import { downloadConsentPdf } from "@shared/consent/downloadConsentPdf";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import { useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Input,
  List,
  Modal,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

const { Text } = Typography;

interface MemberConsentsCardProps {
  memberId: string;
  /** True when the viewer is the member themselves (vs office staff). */
  isSelfView?: boolean;
}

/**
 * Lists every ConsentRecord for the member, with a revoke action on
 * each still-active row.
 *
 * Server-side scoping: members only ever see their own consents
 * (``scope_to_member`` in the viewset). Office staff see all consents
 * tenant-wide, so for them we narrow client-side to ``memberId``.
 *
 * Once the next ``make generate-api`` regen picks up the
 * ``?member=<id>`` query parameter (declared via ``@extend_schema``
 * on the backend), swap the post-fetch ``.filter`` for passing
 * ``{ params: { member: memberId } }`` into the hook — let the DB
 * narrow instead of the browser.
 */
const MemberConsentsCard = ({
  memberId,
  isSelfView,
}: MemberConsentsCardProps) => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { formatDateTimeWithFallback } = useTimeFormat();
  const [revokeTarget, setRevokeTarget] = useState<ConsentRecord | null>(null);
  const [revokeReason, setRevokeReason] = useState("");

  const { data, isLoading, error } = useCommissioningConsentsList();

  const records = useMemo<ConsentRecord[]>(() => {
    if (!data) return [];
    // ``data`` is ``ConsentRecord[]`` from the unpaginated default
    // shape, but defensive against orval surfacing a paginated
    // wrapper in the future.
    const all: ConsentRecord[] = Array.isArray(data)
      ? data
      : ((data as { results?: ConsentRecord[] }).results ?? []);
    return all.filter((r) => r.member === memberId);
  }, [data, memberId]);

  const revokeMutation = useCommissioningConsentsRevokeCreate({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({
          queryKey: getCommissioningConsentsListQueryKey(),
        });
        // Member cache fields (sepa_consent etc.) change server-side
        // when a record is revoked — refresh the member detail too.
        void queryClient.invalidateQueries({
          queryKey: getCommissioningMembersRetrieveQueryKey(memberId),
        });
        setRevokeTarget(null);
        setRevokeReason("");
      },
      // Without this, a failed revoke gave no feedback — the modal stays open
      // (revokeTarget is only cleared on success) but the user saw nothing.
      onError: (err) => notify.error(getErrorMessage(err)),
    },
  });

  const renderKindTag = (kind: ConsentDocumentSummary["kind"] | undefined) => {
    if (!kind) return null;
    const colour: Record<string, string> = {
      privacy: "blue",
      sepa: "geekblue",
      withdrawal: "orange",
      terms: "purple",
    };
    return (
      <Tag color={colour[kind] || "default"}>{t(`consent.kind.${kind}`)}</Tag>
    );
  };

  if (isLoading) {
    return (
      <Card
        title={t("consent.card_title")}
        className="member-card--blue-title"
        style={{ marginTop: 24 }}
      >
        <Spin />
      </Card>
    );
  }

  if (error) {
    return (
      <Card
        title={t("consent.card_title")}
        className="member-card--blue-title"
        style={{ marginTop: 24 }}
      >
        <Alert type="error" showIcon message={t("consent.load_error")} />
      </Card>
    );
  }

  return (
    <Card
      title={t("consent.card_title")}
      className="member-card--blue-title blue-border"
      style={{ marginTop: 24 }}
    >
      {records.length === 0 ? (
        // Just the explanatory text — no big placeholder icon.
        <Text type="secondary">{t("consent.empty")}</Text>
      ) : (
        <List<ConsentRecord>
          dataSource={records}
          renderItem={(record) => {
            const active = record.is_active;
            return (
              <List.Item
                actions={[
                  <Button
                    key="download"
                    size="small"
                    icon={<DownloadOutlined />}
                    onClick={() => downloadConsentPdf(record.document?.id)}
                    disabled={!record.document?.id}
                  >
                    {t("consent.download")}
                  </Button>,
                  ...(active
                    ? [
                        <Button
                          key="revoke"
                          danger
                          size="small"
                          icon={<StopOutlined />}
                          onClick={() => setRevokeTarget(record)}
                        >
                          {t("consent.revoke")}
                        </Button>,
                      ]
                    : []),
                ]}
              >
                <List.Item.Meta
                  avatar={
                    active ? (
                      <CheckCircleOutlined
                        style={{ color: "var(--color-success)", fontSize: 20 }}
                      />
                    ) : (
                      <CloseCircleOutlined
                        style={{
                          color: "var(--color-text-tertiary)",
                          fontSize: 20,
                        }}
                      />
                    )
                  }
                  title={
                    <Space wrap>
                      {renderKindTag(record.document?.kind)}
                      <Text strong>
                        {record.document?.title ||
                          `${record.document?.version ?? ""}`}
                      </Text>
                      <Text type="secondary">v{record.document?.version}</Text>
                    </Space>
                  }
                  description={
                    <Space direction="vertical" size={0}>
                      <Text>
                        {t("consent.consented_at")}:{" "}
                        {formatDateTimeWithFallback(record.consented_at, "—")}
                      </Text>
                      {!active && record.revoked_at && (
                        <Text type="danger">
                          {t("consent.revoked_at")}:{" "}
                          {formatDateTimeWithFallback(record.revoked_at, "—")}
                          {record.revoked_reason
                            ? ` — ${record.revoked_reason}`
                            : ""}
                        </Text>
                      )}
                    </Space>
                  }
                />
              </List.Item>
            );
          }}
        />
      )}

      <Modal
        open={!!revokeTarget}
        title={t("consent.revoke_title")}
        onCancel={() => {
          setRevokeTarget(null);
          setRevokeReason("");
        }}
        onOk={() => {
          if (revokeTarget?.id) {
            revokeMutation.mutate({
              id: revokeTarget.id,
              data: { reason: revokeReason } satisfies ConsentRecordRevoke,
            });
          }
        }}
        okButtonProps={{
          danger: true,
          loading: revokeMutation.isPending,
        }}
        okText={t("consent.revoke")}
      >
        <Space direction="vertical" className="w-full">
          <Alert
            type="warning"
            showIcon
            message={t(
              isSelfView
                ? "consent.revoke_warning"
                : "consent.revoke_warning_staff",
              { defaultValue: t("consent.revoke_warning") },
            )}
          />
          <Input.TextArea
            rows={3}
            value={revokeReason}
            onChange={(e) => setRevokeReason(e.target.value)}
            placeholder={t("consent.revoke_reason_placeholder")}
            maxLength={200}
            showCount
          />
        </Space>
      </Modal>
    </Card>
  );
};

export default MemberConsentsCard;
