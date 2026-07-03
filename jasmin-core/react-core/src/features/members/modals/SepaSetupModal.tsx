import { useQueryClient } from "@tanstack/react-query";
import { Alert, Form, Input, Modal, Space, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningConsentsCreate,
  getCommissioningConsentsListQueryKey,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  BillingProfile,
  ConsentRecordCreate,
} from "@shared/api/generated/models";
import {
  getPaymentsBillingProfilesListQueryKey,
  usePaymentsBillingProfilesCreate,
  usePaymentsBillingProfilesList,
  usePaymentsBillingProfilesPartialUpdate,
} from "@shared/api/generated/payments-—-billing-profiles/payments-—-billing-profiles";
import ConsentBlock, {
  ConsentDocumentKind,
} from "@shared/consent/ConsentBlock";
import { ModalCancelSaveFooter } from "@shared/modals/shared";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";

const { Paragraph, Text } = Typography;

interface SepaSetupModalProps {
  open: boolean;
  memberId: string;
  onClose: () => void;
}

interface FormValues {
  iban: string;
  account_holder: string;
}

/**
 * One-shot SEPA mandate setup for a member.
 *
 * Workflow:
 *   1. Show the current SEPA mandate text via ``<ConsentBlock kind="sepa">``.
 *   2. Collect IBAN / BIC / account holder name.
 *   3. On submit:
 *       a. Create or update the BillingProfile.
 *       b. POST a ConsentRecord referencing the same SEPA document the
 *          member just saw, so the audit trail captures *which* version
 *          of the mandate text they accepted.
 *
 * If a BillingProfile already exists for this member the form
 * pre-fills + uses PATCH on submit. A previous SEPA consent on file
 * does NOT block re-recording — re-signing a mandate (changed IBAN,
 * new bank) is a new event and deserves a new ConsentRecord.
 */
export default function SepaSetupModal({
  open,
  memberId,
  onClose,
}: SepaSetupModalProps) {
  const { t, i18n } = useTranslation();
  const [form] = Form.useForm<FormValues>();
  const queryClient = useQueryClient();
  const [sepaDocId, setSepaDocId] = useState<string | undefined>(undefined);
  const [sepaAccepted, setSepaAccepted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const { data: profiles } = usePaymentsBillingProfilesList(
    { member: memberId },
    { query: { enabled: open } },
  );
  const existing = useMemo<BillingProfile | undefined>(() => {
    if (!profiles) return undefined;
    // Server filters to this member (one profile per member), so take the first.
    const all: BillingProfile[] = Array.isArray(profiles)
      ? profiles
      : ((profiles as { results?: BillingProfile[] }).results ?? []);
    return all[0];
  }, [profiles]);

  useEffect(() => {
    // The decrypted iban / account_holder are no longer returned by the API
    // (they're masked on read). Re-signing a mandate means entering the IBAN
    // again anyway, so the form always starts empty; the current value is
    // shown masked in the existing-profile notice below.
    form.resetFields();
  }, [existing, form]);

  const createMutation = usePaymentsBillingProfilesCreate();
  const patchMutation = usePaymentsBillingProfilesPartialUpdate();

  const handleSubmit = async () => {
    setSubmitError(null);
    let values: FormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    if (!sepaAccepted || !sepaDocId) {
      setSubmitError(t("sepa.must_accept_mandate"));
      return;
    }

    setSubmitting(true);
    try {
      // Step 1: upsert BillingProfile.
      const signedAt = new Date().toISOString().slice(0, 10);
      if (existing?.id) {
        await patchMutation.mutateAsync({
          id: existing.id,
          data: {
            iban: values.iban,
            account_holder: values.account_holder,
            sepa_mandate_signed_at: signedAt,
          } as BillingProfile,
        });
      } else {
        await createMutation.mutateAsync({
          data: {
            member: memberId,
            iban: values.iban,
            account_holder: values.account_holder,
            sepa_mandate_signed_at: signedAt,
            is_active: true,
          } as BillingProfile,
        });
      }

      // Step 2: record the SEPA consent against the exact document
      // version the member just saw via the ConsentBlock above.
      // Office staff calling this modal need to pin the target via
      // ``member``; member-role callers are pinned server-side
      // regardless of what's sent.
      //
      // NOTE: the cast goes away after the next ``make generate-api``
      // — I added ``member`` to ``ConsentRecordCreateSerializer`` so
      // the regenerated type will include it.
      await commissioningConsentsCreate({
        document_id: sepaDocId,
        member: memberId,
      } as ConsentRecordCreate & { member: string });

      void queryClient.invalidateQueries({
        queryKey: getPaymentsBillingProfilesListQueryKey(),
      });
      void queryClient.invalidateQueries({
        queryKey: getCommissioningConsentsListQueryKey(),
      });
      notify.success(t("sepa.saved"));
      onClose();
      // Reset local state so re-opening the modal starts fresh.
      setSepaAccepted(false);
      setSepaDocId(undefined);
    } catch (err) {
      // Translated message by error code where we have one (e.g. a domain
      // error), falling back to the unwrapped axios message.
      setSubmitError(getErrorMessage(err, t("common.error")));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      title={t("sepa.setup_title")}
      onCancel={onClose}
      footer={
        <ModalCancelSaveFooter
          onCancel={onClose}
          onPrimary={handleSubmit}
          loading={submitting}
          primaryLabel={t("sepa.save")}
        />
      }
      width={640}
    >
      <Space direction="vertical" size="middle" className="w-full">
        {existing && (
          <Space direction="vertical" size={2} className="w-full">
            <Paragraph type="secondary">
              {t("sepa.existing_profile_notice")}
            </Paragraph>
            {(existing.iban_masked || existing.account_holder_masked) && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                {t("sepa.current_mandate")}: {existing.account_holder_masked}
                {existing.account_holder_masked && existing.iban_masked
                  ? " · "
                  : ""}
                {existing.iban_masked}
              </Text>
            )}
          </Space>
        )}
        <Paragraph type="secondary">{t("sepa.setup_intro")}</Paragraph>

        <ConsentBlock
          kind={ConsentDocumentKind.sepa}
          locale={i18n.language || "de"}
          checked={sepaAccepted}
          onChange={(checked, docId) => {
            setSepaAccepted(checked);
            setSepaDocId(docId);
          }}
        />

        <Form<FormValues> form={form} layout="vertical">
          <Form.Item
            label="IBAN"
            name="iban"
            rules={[
              {
                required: true,
                message: t("sepa.iban_required"),
              },
              {
                pattern: /^[A-Z0-9 ]{15,34}$/i,
                message: t("sepa.iban_invalid"),
              },
            ]}
          >
            <Input
              placeholder="DE89 3704 0044 0532 0130 00"
              autoComplete="off"
            />
          </Form.Item>
          <Form.Item
            label={t("sepa.account_holder")}
            name="account_holder"
            rules={[
              {
                required: true,
                message: t("sepa.account_holder_required"),
              },
            ]}
          >
            <Input autoComplete="off" />
          </Form.Item>
        </Form>

        {submitError && <Alert type="error" showIcon message={submitError} />}
      </Space>
    </Modal>
  );
}
