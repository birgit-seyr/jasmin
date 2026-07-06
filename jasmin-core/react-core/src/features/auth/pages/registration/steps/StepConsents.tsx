import { Alert, Button, Flex, Space, Typography } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { StepProps } from "../types";
import ConsentDocumentField from "@shared/consent/ConsentDocumentField";
import { useCurrentConsentDoc } from "@shared/consent/useCurrentConsentDoc";

const { Paragraph } = Typography;

const KINDS = ["privacy", "withdrawal"] as const;

/**
 * Step 3 — privacy + withdrawal consents. A checkbox is shown (and required)
 * only for kinds the tenant has actually published; each links to the
 * document's PDF and records the accepted document id.
 */
export default function StepConsents({ data, update, next, back }: StepProps) {
  const { t } = useTranslation();
  const privacy = useCurrentConsentDoc("privacy");
  const withdrawal = useCurrentConsentDoc("withdrawal");
  const docs = { privacy: privacy.doc, withdrawal: withdrawal.doc };
  // A still-loading query has ``doc === undefined``, which looks identical to
  // "no document published" — Next must not proceed (it would skip a required
  // consent) until the fetches settle.
  const loading = privacy.isLoading || withdrawal.isLoading;

  const [accepted, setAccepted] = useState<Record<string, string | undefined>>(
    () => ({
      privacy: data.accepted_consent_documents?.privacy,
      withdrawal: data.accepted_consent_documents?.withdrawal,
    }),
  );
  const [error, setError] = useState("");

  const setKind = (kind: string, docId: string | undefined, checked: boolean) =>
    setAccepted((prev) => ({ ...prev, [kind]: checked ? docId : undefined }));

  const handleNext = () => {
    if (loading) return;
    const missing = KINDS.filter((k) => docs[k] && !accepted[k]);
    if (missing.length > 0) {
      setError(t("auth.registration.consents.must_accept_all"));
      return;
    }
    setError("");
    const kept: Record<string, string> = {};
    for (const k of KINDS) {
      const id = accepted[k];
      if (docs[k] && id) kept[k] = id;
    }
    update({
      accepted_consent_documents: {
        ...data.accepted_consent_documents,
        ...kept,
      },
    });
    next();
  };

  return (
    <>
      <Paragraph>{t("auth.registration.consents.intro")}</Paragraph>
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        {privacy.doc && (
          <ConsentDocumentField
            doc={privacy.doc}
            accepted={Boolean(accepted.privacy)}
            onChange={(checked) => setKind("privacy", privacy.doc?.id, checked)}
            labelKey="auth.registration.consents.accept_privacy"
          />
        )}
        {withdrawal.doc && (
          <ConsentDocumentField
            doc={withdrawal.doc}
            accepted={Boolean(accepted.withdrawal)}
            onChange={(checked) =>
              setKind("withdrawal", withdrawal.doc?.id, checked)
            }
            labelKey="auth.registration.consents.accept_withdrawal"
          />
        )}
      </Space>

      {error && (
        <Alert
          type="error"
          showIcon
          message={error}
          style={{ marginTop: 12 }}
        />
      )}

      <Flex justify="space-between" style={{ marginTop: 16 }}>
        <Button onClick={back}>{t("auth.registration.actions.back")}</Button>
        <Button
          type="primary"
          onClick={handleNext}
          loading={loading}
          disabled={loading}
        >
          {t("auth.registration.actions.next")}
        </Button>
      </Flex>
    </>
  );
}
