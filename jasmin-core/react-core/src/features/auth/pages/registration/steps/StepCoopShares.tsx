import { Alert, Button, Flex, Form, InputNumber, Typography } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useCurrency, useTenant } from "@hooks/index";
import type { StepProps } from "../types";
import ConsentDocumentField from "../components/ConsentDocumentField";
import { useCurrentConsentDoc } from "../components/useCurrentConsentDoc";

const { Paragraph, Text } = Typography;

/**
 * Step 1 — cooperative shares. The applicant picks how many shares to
 * subscribe (bounded by the tenant's min/max) and accepts the
 * Zeichnungsvertrag (``coop_contract`` consent). When the tenant requires a
 * paper signature, the checkbox is an acknowledgement and a print-and-mail
 * hint is shown.
 */
export default function StepCoopShares({ data, update, next }: StepProps) {
  const { t } = useTranslation();
  const { tenant } = useTenant();
  const { formatCurrency } = useCurrency();
  const { doc: contractDoc, isLoading: contractLoading } =
    useCurrentConsentDoc("coop_contract");

  const min = Number(tenant?.min_number_coop_shares ?? 1) || 1;
  const max = Number(tenant?.max_number_coop_shares ?? 100) || 100;
  const shareValue = Number(tenant?.value_one_coop_share ?? 0);
  const paperRequired = tenant?.requires_paper_signature_for_membership === true;

  const [count, setCount] = useState<number>(data.coop_shares_count ?? min);
  const [contractAccepted, setContractAccepted] = useState<boolean>(
    Boolean(data.accepted_consent_documents?.coop_contract),
  );
  const [error, setError] = useState("");

  const total = shareValue ? count * shareValue : 0;

  const handleNext = () => {
    // Don't advance while the consent doc is still loading — an undefined
    // ``contractDoc`` looks the same as "no contract required" and would let
    // the required Zeichnungsvertrag consent be skipped.
    if (contractLoading) return;
    if (count < min || count > max) {
      setError(t("auth.registration.coop.count_out_of_range", { min, max }));
      return;
    }
    if (contractDoc && !contractAccepted) {
      setError(t("auth.registration.coop.must_accept_contract"));
      return;
    }
    setError("");
    update({
      coop_shares_count: count,
      accepted_consent_documents: {
        ...data.accepted_consent_documents,
        ...(contractDoc && contractAccepted
          ? { coop_contract: contractDoc.id }
          : {}),
      },
    });
    next();
  };

  return (
    <>
      <Paragraph>{t("auth.registration.coop.intro", { min, max })}</Paragraph>

      <Form layout="vertical">
        <Form.Item label={t("auth.registration.coop.shares_label")}>
          <InputNumber
            min={min}
            max={max}
            value={count}
            onChange={(v) => setCount(Number(v) || min)}
            className="w-full"
          />
        </Form.Item>

        {shareValue > 0 && (
          <Paragraph type="secondary">
            {t("auth.registration.coop.total")}: {formatCurrency(total)}{" "}
            <Text type="secondary">
              ({count} × {formatCurrency(shareValue)})
            </Text>
          </Paragraph>
        )}

        {contractDoc && (
          <Form.Item>
            <ConsentDocumentField
              doc={contractDoc}
              accepted={contractAccepted}
              onChange={setContractAccepted}
              labelKey={
                paperRequired
                  ? "auth.registration.coop.contract_ack_prefix"
                  : "auth.registration.coop.contract_accept_prefix"
              }
            />
            {paperRequired && (
              <Alert
                style={{ marginTop: 8 }}
                type="info"
                showIcon
                message={t("auth.registration.coop.paper_hint")}
              />
            )}
          </Form.Item>
        )}

        {error && (
          <Alert
            type="error"
            showIcon
            message={error}
            style={{ marginBottom: 12 }}
          />
        )}

        <Flex justify="flex-end">
          <Button
            type="primary"
            onClick={handleNext}
            loading={contractLoading}
            disabled={contractLoading}
          >
            {t("auth.registration.actions.next")}
          </Button>
        </Flex>
      </Form>
    </>
  );
}
