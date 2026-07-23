import { Tag, Typography } from "antd";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { usePaymentsBillingProfilesList } from "@shared/api/generated/payments-—-billing-profiles/payments-—-billing-profiles";
import type { BillingProfile } from "@shared/api/generated/models";
import { PaymentMethodEnum } from "@shared/api/generated/models";
import { ExplainerText } from "@shared/ui";
import { EditableTable, READ_ONLY_PERMISSION } from "@shared/tables";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { useDateFormat } from "@hooks/index";

const { Text } = Typography;

type SepaMandateRow = BillingProfile & TableRecord;

// ISO date strings sort lexically, so a plain string compare is a correct date
// sorter. Null/empty values sort last (ascending) via the "" fallback.
const byString = (
  field: keyof SepaMandateRow,
): ((a: SepaMandateRow, b: SepaMandateRow) => number) => {
  return (a, b) =>
    String(a[field] ?? "").localeCompare(String(b[field] ?? ""));
};

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

  // Office scope: the list returns every member's profile (IBAN + account
  // holder masked in bulk reads). Show every profile that HAS a SEPA mandate —
  // either currently on SEPA, or one that was withdrawn (Art. 7(3) consent
  // revoke switches the profile off SEPA to BANK_TRANSFER but keeps the mandate
  // reference / signed date). Filtering on payment_method alone would make a
  // revoked mandate silently disappear, as if it had been deleted.
  const { data: profiles, isLoading } = usePaymentsBillingProfilesList();

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
        sorter: byString("member_string"),
        defaultSortOrder: "ascend",
      },
      {
        title: t("sepa.mandate_reference"),
        dataIndex: "sepa_mandate_reference",
        key: "sepa_mandate_reference",
        sorter: byString("sepa_mandate_reference"),
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
        sorter: byString("sepa_mandate_signed_at"),
        render: (value) => formatDate(value as string | null),
      },
      {
        title: t("sepa.first_use_at"),
        dataIndex: "sepa_mandate_first_use_at",
        key: "sepa_mandate_first_use_at",
        align: "center",
        sorter: byString("sepa_mandate_first_use_at"),
        render: (value) => formatDate(value as string | null),
      },
      {
        title: t("sepa.paper_received_at"),
        dataIndex: "sepa_mandate_paper_received_at",
        key: "sepa_mandate_paper_received_at",
        align: "center",
        sorter: byString("sepa_mandate_paper_received_at"),
        render: (value) => formatDate(value as string | null),
      },
      {
        title: t("sepa.status"),
        dataIndex: "is_sepa_ready",
        key: "is_sepa_ready",
        align: "center",
        render: (_value, record) => {
          // A mandate reference on a profile that is no longer SEPA means the
          // mandate was withdrawn (consent revoke → BANK_TRANSFER). Show it as
          // revoked rather than hiding it.
          if (record.payment_method !== PaymentMethodEnum.SEPA_DD) {
            return <Tag color="red">{t("sepa.status_revoked")}</Tag>;
          }
          if (!record.is_active) {
            return <Tag color="default">{t("sepa.status_inactive")}</Tag>;
          }
          if (record.is_sepa_ready) {
            return <Tag color="green">{t("sepa.status_ready")}</Tag>;
          }
          return <Tag color="orange">{t("sepa.status_incomplete")}</Tag>;
        },
      },
      {
        title: t("sepa.notes"),
        dataIndex: "notes",
        key: "notes",
        render: (value) => (value as string) || "",
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
    </div>
  );
}
