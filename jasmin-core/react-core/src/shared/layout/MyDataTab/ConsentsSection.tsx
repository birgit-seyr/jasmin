import { EyeOutlined, StopOutlined } from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Descriptions,
  Flex,
  Input,
  Modal,
  Skeleton,
  Space,
  Typography,
} from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  getGdprMyDataRetrieveQueryKey,
  useGdprMyDataRetrieve,
} from "@shared/api/generated/gdpr/gdpr";
import {
  useCommissioningConsentDocumentsCurrentRetrieve,
  useCommissioningConsentsRevokeCreate,
} from "@shared/api/generated/commissioning/commissioning";
import { CommissioningConsentDocumentsCurrentRetrieveKind } from "@shared/api/generated/models";
import { useLocale } from "@shared/contexts/LocalContext";
import { useDateFormat } from "@hooks/index";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";

const { Title, Paragraph, Text } = Typography;

// Kinds the backend's ``consent_documents/current/`` endpoint can
// resolve to a downloadable doc. Other kinds still render in the list
// (with the date), they just don't get a "view text" button.
const VIEWABLE_CONSENT_KINDS = new Set<string>(
  Object.values(CommissioningConsentDocumentsCurrentRetrieveKind),
);

type ConsentDocKind =
  (typeof CommissioningConsentDocumentsCurrentRetrieveKind)[keyof typeof CommissioningConsentDocumentsCurrentRetrieveKind];

/**
 * Read-only consents list for the "Meine Daten" tab. Pulls
 * ``gdpr/my_data/`` for the user's consent history and exposes a small
 * "Text anzeigen" button per row that opens
 * {@link ConsentDocumentModal} for the four kinds the backend can
 * serve (``privacy`` / ``sepa`` / ``withdrawal`` / ``terms``).
 *
 * The modal renders the *current* document for that kind in the
 * active locale — not necessarily the exact historical version the
 * user clicked. The SAR bundle exposes ``document_version`` if/when
 * we want to pin to that specific revision later.
 */
export default function ConsentsSection() {
  const { t } = useTranslation();
  const { language } = useLocale();
  const { formatDateWithFallback } = useDateFormat();
  const queryClient = useQueryClient();
  const { data: sar } = useGdprMyDataRetrieve();
  const consents = sar?.consents ?? [];

  const [viewingKind, setViewingKind] = useState<string | null>(null);
  // Art. 7(3): a member must be able to withdraw consent as easily as giving
  // it. The backend scopes revoke to the caller's own records.
  const [revokeTargetId, setRevokeTargetId] = useState<string | null>(null);
  const [revokeReason, setRevokeReason] = useState("");

  const revokeMutation = useCommissioningConsentsRevokeCreate({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({
          queryKey: getGdprMyDataRetrieveQueryKey(),
        });
        setRevokeTargetId(null);
        setRevokeReason("");
      },
      onError: (err) => notify.error(getErrorMessage(err)),
    },
  });

  return (
    <div>
      <Title level={5}>{t("gdpr.consents")}</Title>
      {consents.length === 0 ? (
        <Paragraph type="secondary">{t("gdpr.no_consents")}</Paragraph>
      ) : (
        <Descriptions column={1} bordered size="small">
          {consents.map((c, idx) => (
            <Descriptions.Item
              key={idx}
              label={
                <Space>
                  <span>{t(`gdpr.consent_kind_${c.kind}`)}</span>
                  {VIEWABLE_CONSENT_KINDS.has(c.kind) && (
                    <Button
                      size="small"
                      type="link"
                      icon={<EyeOutlined />}
                      onClick={() => setViewingKind(c.kind)}
                    >
                      {t("gdpr.view_consent_text")}
                    </Button>
                  )}
                </Space>
              }
            >
              {c.revoked_at ? (
                <Space direction="vertical" size={0}>
                  <Text>
                    {t("gdpr.consent_revoked_at")}:{" "}
                    {formatDateWithFallback(c.revoked_at)}
                  </Text>
                  <Text type="secondary">
                    {t("gdpr.consent_given_at")}:{" "}
                    {formatDateWithFallback(c.consented_at)}
                  </Text>
                </Space>
              ) : (
                <Flex justify="space-between" align="center">
                  <Text>
                    {t("gdpr.consent_given_at")}:{" "}
                    {formatDateWithFallback(c.consented_at)}
                  </Text>
                  <Button
                    danger
                    size="small"
                    icon={<StopOutlined />}
                    onClick={() => setRevokeTargetId(c.id)}
                  >
                    {t("consent.revoke")}
                  </Button>
                </Flex>
              )}
            </Descriptions.Item>
          ))}
        </Descriptions>
      )}

      <Modal
        open={revokeTargetId !== null}
        title={t("consent.revoke_title")}
        onCancel={() => {
          setRevokeTargetId(null);
          setRevokeReason("");
        }}
        onOk={() => {
          if (revokeTargetId) {
            revokeMutation.mutate({
              id: revokeTargetId,
              data: { reason: revokeReason },
            });
          }
        }}
        okButtonProps={{ danger: true, loading: revokeMutation.isPending }}
        okText={t("consent.revoke")}
      >
        <Space direction="vertical" className="w-full">
          <Alert type="warning" showIcon message={t("consent.revoke_warning")} />
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

      {viewingKind && (
        <ConsentDocumentModal
          kind={viewingKind as ConsentDocKind}
          locale={language || "de"}
          onClose={() => setViewingKind(null)}
        />
      )}
    </div>
  );
}

function ConsentDocumentModal({
  kind,
  locale,
  onClose,
}: {
  kind: ConsentDocKind;
  locale: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const { formatDateWithFallback } = useDateFormat();
  const { data, isLoading, error } =
    useCommissioningConsentDocumentsCurrentRetrieve(
      { kind, locale },
      { query: { retry: false } },
    );

  return (
    <Modal
      open
      onCancel={onClose}
      onOk={onClose}
      width={720}
      title={data?.title || t(`gdpr.consent_kind_${kind}`)}
      footer={null}
    >
      {isLoading ? (
        <Skeleton active paragraph={{ rows: 6 }} />
      ) : error || !data ? (
        <Alert
          type="error"
          showIcon
          message={t("consent.block.missing_document_title")}
        />
      ) : (
        <>
          <div
            style={{
              maxHeight: 360,
              overflowY: "auto",
              padding: 12,
              border: "1px solid var(--ant-color-border, #d9d9d9)",
              borderRadius: 4,
              background: "var(--ant-color-bg-container, #fafafa)",
              whiteSpace: "pre-wrap",
              fontSize: 13,
            }}
          >
            {data.body}
          </div>
          <Paragraph
            type="secondary"
            style={{ fontSize: 11, marginTop: 8, marginBottom: 0 }}
          >
            {t("consent.block.version_label")} {data.version}
            {data.valid_from
              ? ` · ${t("consent.block.effective_label")} ${formatDateWithFallback(data.valid_from)}`
              : ""}
          </Paragraph>
        </>
      )}
    </Modal>
  );
}
