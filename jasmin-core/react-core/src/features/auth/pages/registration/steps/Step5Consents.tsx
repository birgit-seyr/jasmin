import { useMemo } from "react";
import { Alert, Button, Flex, Space, Typography } from "antd";
import { useTranslation } from "react-i18next";
import ConsentBlock, {
  ConsentDocumentKind,
} from "@shared/consent/ConsentBlock";
import type { StepProps } from "../types";

const { Title, Paragraph } = Typography;

/** The set of consents we require at registration time. SEPA is NOT
 * captured here — it's collected later when the member sets up a
 * SEPA Direct Debit mandate, alongside the IBAN. */
const REQUIRED_KINDS = [
  ConsentDocumentKind.privacy,
  ConsentDocumentKind.withdrawal,
  ConsentDocumentKind.terms,
] as const;

export default function Step5Consents({
  data,
  update,
  next,
  back,
}: StepProps) {
  const { t, i18n } = useTranslation();
  // Memoised so the ``useMemo`` below sees a stable reference between
  // renders — without this, the ``?? {}`` fallback would synthesise a
  // fresh object every render and lint flags it as a dependency
  // instability.
  const accepted = useMemo(
    () => data.accepted_consent_documents ?? {},
    [data.accepted_consent_documents],
  );

  const handleChange = (
    kind: string,
    checked: boolean,
    documentId: string | undefined,
  ) => {
    const updated = { ...accepted };
    if (checked && documentId) {
      updated[kind] = documentId;
    } else {
      delete updated[kind];
    }
    update({ accepted_consent_documents: updated });
  };

  // ``next`` only unlocks once every required kind has an accepted
  // document_id captured — guarantees we have proof-of-version for
  // each consent before letting the user move on.
  const allAccepted = useMemo(
    () => REQUIRED_KINDS.every((kind) => !!accepted[kind]),
    [accepted],
  );

  return (
    <>
      <Title level={4}>{t("auth.registration.step5_consents.title")}</Title>
      <Paragraph type="secondary">
        {t("auth.registration.step5_consents.subtitle")}
      </Paragraph>

      <Space direction="vertical" size="middle" className="w-full">
        {REQUIRED_KINDS.map((kind) => (
          <ConsentBlock
            key={kind}
            kind={kind}
            locale={i18n.language || "de"}
            checked={!!accepted[kind]}
            onChange={(checked, documentId) =>
              handleChange(kind, checked, documentId)
            }
          />
        ))}
      </Space>

      {!allAccepted && (
        <Alert
          type="info"
          showIcon
          style={{ marginTop: 16 }}
          message={t("auth.registration.step5_consents.must_accept_all")}
        />
      )}

      <Flex justify="space-between" gap="small" style={{ marginTop: 16 }}>
        <Button onClick={back}>{t("auth.registration.actions.back")}</Button>
        <Button type="primary" onClick={next} disabled={!allAccepted}>
          {t("auth.registration.actions.next")}
        </Button>
      </Flex>
    </>
  );
}
