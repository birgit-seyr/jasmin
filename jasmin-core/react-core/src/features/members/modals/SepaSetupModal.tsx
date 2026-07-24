import { useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Checkbox,
  DatePicker,
  Form,
  Input,
  Modal,
  Space,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useDateFormat } from "@hooks/configuration/useDateFormat";
import { useTenant } from "@hooks/configuration/useTenant";
import {
  commissioningConsentsCreate,
  getCommissioningConsentsListQueryKey,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  BillingProfile,
  ConsentRecordCreate,
} from "@shared/api/generated/models";
import { PaymentMethodEnum } from "@shared/api/generated/models";
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
import { notify, unwrapList } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";

const { Paragraph, Text } = Typography;

interface SepaSetupModalProps {
  open: boolean;
  memberId: string;
  onClose: () => void;
  /** Office mode: expose the office-only fields — an editable signed date
   *  (default today) and, when the tenant requires a paper signature, a
   *  "paper signature received" checkbox that records
   *  ``sepa_mandate_paper_received_at``. Off (member self-service) keeps the
   *  original "sign now" behaviour. */
  officeMode?: boolean;
  /** Called after a successful upsert (before ``onClose``). Lets callers that
   *  read a DIFFERENT query than the billing-profiles list — e.g. the Abos SEPA
   *  square's ``mandate_status`` — refresh it. */
  onSaved?: () => void;
}

interface FormValues {
  iban: string;
  account_holder: string;
  /** Office-only: a manually-set mandate reference. Blank → the backend
   *  auto-generates one on save. */
  sepa_mandate_reference?: string;
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
  officeMode = false,
  onSaved,
}: SepaSetupModalProps) {
  const { t, i18n } = useTranslation();
  const { getSetting } = useTenant();
  const { dateFormat } = useDateFormat();
  const [form] = Form.useForm<FormValues>();
  const queryClient = useQueryClient();
  const [sepaDocId, setSepaDocId] = useState<string | undefined>(undefined);
  const [sepaAccepted, setSepaAccepted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  // Office-only fields (see ``officeMode``). Signed date defaults to today; the
  // paper checkbox only appears when the tenant requires a paper signature.
  const [signedDate, setSignedDate] = useState<Dayjs>(dayjs());
  const [paperReceived, setPaperReceived] = useState(false);
  const requiresPaperSignature = Boolean(
    getSetting("requires_paper_signature_for_sepa_mandate", false),
  );

  const { data: profiles } = usePaymentsBillingProfilesList(
    { member: memberId },
    { query: { enabled: open } },
  );
  const existing = useMemo<BillingProfile | undefined>(() => {
    // Server filters to this member (one profile per member), so take the first.
    return unwrapList<BillingProfile>(profiles)[0];
  }, [profiles]);

  useEffect(() => {
    // Reset EVERYTHING each time the modal opens (and re-seed when the profile
    // loads). The modal is a PERSISTENT instance in some callers (e.g. the Abos
    // SEPA square), so without this a prior member's ticked consent, stale
    // error, or office-field edits would carry over — and the affirmative
    // click-consent gate could be silently pre-satisfied for the next member.
    if (!open) return;
    // The decrypted iban / account_holder are no longer returned by the API
    // (they're masked on read). Re-signing a mandate means entering the IBAN
    // again anyway, so the form always starts empty; the current value is shown
    // masked in the existing-profile notice below.
    form.resetFields();
    setSepaAccepted(false);
    setSepaDocId(undefined);
    setSubmitError(null);
    // Seed the office fields from any existing mandate (signed date, whether a
    // paper signature is already on file, the mandate reference); default to
    // today / unchecked / blank.
    setSignedDate(
      existing?.sepa_mandate_signed_at
        ? dayjs(existing.sepa_mandate_signed_at)
        : dayjs(),
    );
    setPaperReceived(Boolean(existing?.sepa_mandate_paper_received_at));
    if (officeMode) {
      form.setFieldsValue({
        sepa_mandate_reference: existing?.sepa_mandate_reference ?? undefined,
      });
    }
  }, [open, existing, form, officeMode]);

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
    // Member mode needs the accepted consent DOCUMENT (recorded below); office
    // mode replaces the click-through document with a plain attestation
    // checkbox (the office holds the signed PAPER mandate), so it only needs
    // the checkbox — no ConsentRecord is created for a paper mandate.
    if (!sepaAccepted || (!officeMode && !sepaDocId)) {
      setSubmitError(t("sepa.must_accept_mandate"));
      return;
    }

    setSubmitting(true);
    try {
      // Step 1: upsert BillingProfile.
      const today = dayjs().format("YYYY-MM-DD");
      // Office mode lets the office backdate the signature (paper mandate);
      // member self-service always signs "now".
      const signedAt = officeMode ? signedDate.format("YYYY-MM-DD") : today;
      // Paper-signature confirmation: only relevant in office mode with the
      // tenant setting on. Checked → record the received date (keep an existing
      // one, else today); unchecked → clear it.
      const paperFields =
        officeMode && requiresPaperSignature
          ? {
              sepa_mandate_paper_received_at: paperReceived
                ? (existing?.sepa_mandate_paper_received_at ?? today)
                : null,
            }
          : {};
      // Office-only: a manually-entered mandate reference overrides the
      // backend's auto-generated one. Blank → omit (backend generates it).
      const referenceField =
        officeMode && values.sepa_mandate_reference?.trim()
          ? { sepa_mandate_reference: values.sepa_mandate_reference.trim() }
          : {};
      if (existing?.id) {
        await patchMutation.mutateAsync({
          id: existing.id,
          data: {
            // Re-arm SEPA: a prior consent-revoke switches the profile to
            // BANK_TRANSFER (keeping the mandate columns). Without resetting
            // payment_method + is_active here, re-doing the setup would update
            // the IBAN/signed date but leave the profile on BANK_TRANSFER, so
            // is_sepa_ready stays false and the "new" mandate never activates.
            // (payment_method into SEPA is step-up gated — the api.ts
            // interceptor handles the challenge transparently.)
            payment_method: PaymentMethodEnum.SEPA_DD,
            is_active: true,
            iban: values.iban,
            account_holder: values.account_holder,
            sepa_mandate_signed_at: signedAt,
            ...paperFields,
            ...referenceField,
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
            ...paperFields,
            ...referenceField,
          } as BillingProfile,
        });
      }

      // Step 2 (member self-service only): record the SEPA consent against the
      // exact document version the member just accepted via the ConsentBlock.
      // Office mode holds a PAPER mandate instead — the paper is the consent
      // artifact (captured by ``sepa_mandate_paper_received_at``), so no
      // digital ConsentRecord is created (a fake click-through would misrepresent
      // how consent was actually given). ``member`` pins the target for office
      // callers; member-role callers are pinned server-side regardless.
      if (!officeMode && sepaDocId) {
        await commissioningConsentsCreate({
          document_id: sepaDocId,
          member: memberId,
        } as ConsentRecordCreate & { member: string });
      }

      void queryClient.invalidateQueries({
        queryKey: getPaymentsBillingProfilesListQueryKey(),
      });
      void queryClient.invalidateQueries({
        queryKey: getCommissioningConsentsListQueryKey(),
      });
      notify.success(t("sepa.saved"));
      onSaved?.();
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
        <Paragraph type="secondary">
          {t(officeMode ? "sepa.office_setup_intro" : "sepa.setup_intro")}
        </Paragraph>

        {officeMode ? (
          // Office records the mandate FOR the member (paper). A plain
          // attestation replaces the member-facing document click-through.
          <Checkbox
            checked={sepaAccepted}
            onChange={(e) => setSepaAccepted(e.target.checked)}
          >
            {t("sepa.office_mandate_confirm")}
          </Checkbox>
        ) : (
          <ConsentBlock
            kind={ConsentDocumentKind.sepa}
            locale={i18n.language || "de"}
            checked={sepaAccepted}
            onChange={(checked, docId) => {
              setSepaAccepted(checked);
              setSepaDocId(docId);
            }}
          />
        )}

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
          {officeMode && (
            <Form.Item
              label={t("sepa.mandate_reference")}
              name="sepa_mandate_reference"
              extra={t("sepa.mandate_reference_auto_hint")}
            >
              <Input autoComplete="off" />
            </Form.Item>
          )}
        </Form>

        {officeMode && (
          <Space direction="vertical" size="small" className="w-full">
            <div>
              <Text>{t("sepa.signed_at")}</Text>
              <DatePicker
                value={signedDate}
                onChange={(date) => date && setSignedDate(date)}
                format={dateFormat}
                allowClear={false}
                aria-label={t("sepa.signed_at")}
                style={{ display: "block", marginTop: 4 }}
              />
            </div>
            {requiresPaperSignature && (
              <Checkbox
                checked={paperReceived}
                onChange={(e) => setPaperReceived(e.target.checked)}
              >
                {t("sepa.paper_signature_received")}
              </Checkbox>
            )}
          </Space>
        )}

        {submitError && <Alert type="error" showIcon message={submitError} />}
      </Space>
    </Modal>
  );
}
