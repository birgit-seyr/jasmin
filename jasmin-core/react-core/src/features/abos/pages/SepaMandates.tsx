import { Button, Typography } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { usePaymentsBillingProfilesList } from "@shared/api/generated/payments-—-billing-profiles/payments-—-billing-profiles";
import type { BillingProfile } from "@shared/api/generated/models";
import { PaymentMethodEnum } from "@shared/api/generated/models";
import { ExplainerText, SepaMandateStatusTag } from "@shared/ui";
import { EditableTable, READ_ONLY_PERMISSION } from "@shared/tables";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { useDateFormat, useTenant } from "@hooks/index";
import { useRoles } from "@shared/auth";
import SepaMandateImportModal from "@features/abos/modals/SepaMandateImportModal";

const { Text } = Typography;

type SepaMandateRow = BillingProfile & TableRecord;

/**
 * Office-only register of every member's SEPA direct-debit mandate (who,
 * reference, IBAN/account holder — masked — and the mandate lifecycle dates).
 * Read-only report: the data lives on ``payments.BillingProfile``; editing a
 * mandate happens on the member's dedicated SEPA-setup modal (step-up gated),
 * not here.
 */
export default function SepaMandates() {
  const { t } = useTranslation();
  const { formatDate } = useDateFormat();
  const { isOffice } = useRoles();
  const { getSetting } = useTenant();
  const uploadAllowed =
    getSetting("allow_upload_for_data_lists", false) === true;
  const [importModalOpen, setImportModalOpen] = useState(false);

  // Office scope: the list returns every member's profile (IBAN + account
  // holder masked in bulk reads). Show every profile that HAS a SEPA mandate —
  // either currently on SEPA, or one that was withdrawn (Art. 7(3) consent
  // revoke switches the profile off SEPA to BANK_TRANSFER but keeps the mandate
  // reference / signed date). Filtering on payment_method alone would make a
  // revoked mandate silently disappear, as if it had been deleted.
  const {
    data: profiles,
    isLoading,
    refetch,
  } = usePaymentsBillingProfilesList();

  const data = useMemo<SepaMandateRow[]>(
    () =>
      (profiles ?? [])
        .filter(
          (profile) =>
            profile.payment_method === PaymentMethodEnum.SEPA_DD ||
            !!profile.sepa_mandate_reference,
        )
        .map((profile) => ({
          ...profile,
          key: profile.id ?? profile.member,
        })),
    [profiles],
  );

  const columns = useMemo<EditableColumnConfig<SepaMandateRow>[]>(
    () => [
      {
        title: t("sepa.member"),
        dataIndex: "member_string",
        key: "member_string",
      },
      {
        title: t("sepa.mandate_reference"),
        dataIndex: "sepa_mandate_reference",
        key: "sepa_mandate_reference",
        width: "18em",
        render: (value) => (value as string | null) || "—",
      },
      {
        title: t("sepa.account_holder"),
        dataIndex: "account_holder_masked",
        key: "account_holder_masked",
        render: (value) => (value as string) || "—",
      },
      {
        title: t("sepa.iban"),
        dataIndex: "iban_masked",
        key: "iban_masked",
        render: (value) => (value as string) || "—",
      },
      {
        title: t("sepa.signed_at"),
        dataIndex: "sepa_mandate_signed_at",
        key: "sepa_mandate_signed_at",
        align: "center",
        width: "8em",
        render: (value) => formatDate(value as string | null),
      },

      {
        title: t("sepa.paper_received_at"),
        dataIndex: "sepa_mandate_paper_received_at",
        key: "sepa_mandate_paper_received_at",
        align: "center",
        width: "8em",
        render: (value) => formatDate(value as string | null),
      },
      {
        title: t("sepa.status"),
        dataIndex: "is_sepa_ready",
        key: "is_sepa_ready",
        align: "center",
        // Shared badge — same states/colours as the Abos SEPA details modal.
        render: (_value, record) => (
          <SepaMandateStatusTag
            paymentMethod={record.payment_method}
            isActive={record.is_active}
            isSepaReady={record.is_sepa_ready}
          />
        ),
      },
    ],
    [t, formatDate],
  );

  return (
    <div>
      <h1>{t("sepa.mandates_title")}</h1>
      <Text type="secondary" style={{ display: "block", marginBottom: 16 }}>
        {t("sepa.mandates_intro")}
      </Text>
      <EditableTable
        columns={columns}
        initialData={data}
        loading={isLoading}
        permissions={READ_ONLY_PERMISSION}
        pagination={true}
        showSearchBar={true}
      />
      <ExplainerText title={t("common.info")}>
        {t("explainers.sepa_mandates")}
      </ExplainerText>

      {isOffice && (
        <div style={{ marginTop: 24 }}>
          <Button size="small" onClick={() => setImportModalOpen(true)}>
            {t("onboarding.sepa_link")}
          </Button>
        </div>
      )}

      <SepaMandateImportModal
        open={importModalOpen}
        onClose={() => setImportModalOpen(false)}
        uploadAllowed={uploadAllowed}
        onUploadSuccess={() => void refetch()}
      />
    </div>
  );
}
