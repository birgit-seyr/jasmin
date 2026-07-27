import { EditOutlined } from "@ant-design/icons";
import { Button, DatePicker, Modal, Popconfirm, Space, Typography } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  usePaymentsBillingProfilesList,
  usePaymentsBillingProfilesPartialUpdate,
} from "@shared/api/generated/payments-—-billing-profiles/payments-—-billing-profiles";
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
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import { MemberSelector } from "@shared/selectors";
import SepaMandateImportModal from "@features/abos/modals/SepaMandateImportModal";
import SepaSetupModal from "@features/members/modals/SepaSetupModal";

const { Paragraph, Text } = Typography;

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
  const { formatDate, dateFormat } = useDateFormat();
  const { isOffice } = useRoles();
  const { getSetting } = useTenant();
  const uploadAllowed =
    getSetting("allow_upload_for_data_lists", false) === true;
  const [importModalOpen, setImportModalOpen] = useState(false);
  // "Add mandate": pick a member, then reuse the office SEPA setup modal.
  const [addPickerOpen, setAddPickerOpen] = useState(false);
  const [pickedMember, setPickedMember] = useState<string | null>(null);
  const [sepaSetupMemberId, setSepaSetupMemberId] = useState<string | null>(
    null,
  );

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

  // Two-way active toggle for a SEPA_DD profile. ``is_active`` is step-up
  // gated on the backend; the api.ts interceptor drives the password prompt +
  // retry, so nothing special is needed here.
  const patchMutation = usePaymentsBillingProfilesPartialUpdate();
  const toggleActive = useCallback(
    async (row: SepaMandateRow, nextActive: boolean) => {
      if (!row.id) return;
      try {
        await patchMutation.mutateAsync({
          id: row.id,
          // ``member`` is read-only on update but the generated body type
          // still lists it as required; send the row's own member (no-op).
          data: { member: row.member, is_active: nextActive },
        });
        notify.success(
          t(nextActive ? "sepa.reactivated" : "sepa.deactivated"),
        );
        void refetch();
      } catch (err) {
        notify.error(getErrorMessage(err, t("common.error")));
      }
    },
    [patchMutation, refetch, t],
  );

  // Office stamps when the signed PAPER mandate arrived. Works for ANY mandate
  // — including one a member set up themselves (no paper field in self-service)
  // — because ``sepa_mandate_paper_received_at`` is not step-up gated and needs
  // no IBAN re-entry (member is read-only on update).
  const [paperRow, setPaperRow] = useState<SepaMandateRow | null>(null);
  const [paperDate, setPaperDate] = useState<dayjs.Dayjs | null>(null);
  const savePaperReceived = useCallback(async () => {
    if (!paperRow?.id) return;
    try {
      await patchMutation.mutateAsync({
        id: paperRow.id,
        data: {
          member: paperRow.member,
          sepa_mandate_paper_received_at: paperDate
            ? paperDate.format("YYYY-MM-DD")
            : null,
        },
      });
      notify.success(t("sepa.paper_saved"));
      setPaperRow(null);
      void refetch();
    } catch (err) {
      notify.error(getErrorMessage(err, t("common.error")));
    }
  }, [paperRow, paperDate, patchMutation, refetch, t]);

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
        width: "10em",
        render: (value: unknown, record: SepaMandateRow) => (
          <Space size={4}>
            <span>{formatDate(value as string | null) || "—"}</span>
            {isOffice && (
              <Button
                type="text"
                size="small"
                icon={<EditOutlined />}
                aria-label={t("sepa.edit_paper_received")}
                onClick={() => {
                  setPaperRow(record);
                  setPaperDate(value ? dayjs(value as string) : null);
                }}
              />
            )}
          </Space>
        ),
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
      ...(isOffice
        ? [
            {
              title: "",
              // No real field — the render works off ``record``; ``id`` is just
              // a placeholder so the column config type-checks.
              dataIndex: "id" as const,
              key: "actions",
              align: "center" as const,
              width: "9em",
              render: (_value: unknown, record: SepaMandateRow) => {
                // A consent-revoked mandate sits on BANK_TRANSFER — a plain
                // is_active flip won't make it usable again, so re-setup goes
                // through the member's SEPA modal (payment_method + mandate).
                if (record.payment_method !== PaymentMethodEnum.SEPA_DD) {
                  return (
                    <Button
                      type="link"
                      size="small"
                      onClick={() => setSepaSetupMemberId(record.member)}
                    >
                      {t("sepa.set_up_again")}
                    </Button>
                  );
                }
                const active = !!record.is_active;
                return (
                  <Popconfirm
                    title={
                      active
                        ? t("sepa.deactivate_confirm")
                        : t("sepa.reactivate_confirm")
                    }
                    okText={active ? t("sepa.deactivate") : t("sepa.reactivate")}
                    cancelText={t("common.cancel")}
                    onConfirm={() => void toggleActive(record, !active)}
                  >
                    <Button type="link" size="small" danger={active}>
                      {active ? t("sepa.deactivate") : t("sepa.reactivate")}
                    </Button>
                  </Popconfirm>
                );
              },
            },
          ]
        : []),
    ],
    [t, formatDate, isOffice, toggleActive],
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
          <Space>
            <Button
              type="primary"
              size="small"
              onClick={() => setAddPickerOpen(true)}
            >
              {t("sepa.add_mandate")}
            </Button>
            <Button size="small" onClick={() => setImportModalOpen(true)}>
              {t("onboarding.sepa_link")}
            </Button>
          </Space>
        </div>
      )}

      <SepaMandateImportModal
        open={importModalOpen}
        onClose={() => setImportModalOpen(false)}
        uploadAllowed={uploadAllowed}
        onUploadSuccess={() => void refetch()}
      />

      {/* Add: pick a member, then hand off to the office SEPA setup modal
          (which owns create/update + the step-up flow). */}
      <Modal
        open={addPickerOpen}
        title={t("sepa.add_mandate")}
        okText={t("common.next")}
        okButtonProps={{ disabled: !pickedMember }}
        onOk={() => {
          if (!pickedMember) return;
          setSepaSetupMemberId(pickedMember);
          setAddPickerOpen(false);
          setPickedMember(null);
        }}
        onCancel={() => {
          setAddPickerOpen(false);
          setPickedMember(null);
        }}
        destroyOnHidden
      >
        <Paragraph type="secondary">
          {t("sepa.add_mandate_pick_member")}
        </Paragraph>
        <MemberSelector
          selectedMember={pickedMember}
          setSelectedMember={setPickedMember}
        />
      </Modal>

      <SepaSetupModal
        open={!!sepaSetupMemberId}
        memberId={sepaSetupMemberId ?? ""}
        officeMode
        onClose={() => setSepaSetupMemberId(null)}
        onSaved={() => void refetch()}
      />

      {/* Stamp when the signed paper mandate arrived — a single-field PATCH,
          usable even for a member-created mandate (no step-up, no IBAN). */}
      <Modal
        open={!!paperRow}
        title={t("sepa.paper_received_at")}
        okText={t("common.save")}
        onOk={() => void savePaperReceived()}
        onCancel={() => setPaperRow(null)}
        confirmLoading={patchMutation.isPending}
        destroyOnHidden
      >
        <Paragraph type="secondary">{t("sepa.paper_received_hint")}</Paragraph>
        <DatePicker
          value={paperDate}
          onChange={setPaperDate}
          format={dateFormat}
          allowClear
          style={{ width: "100%" }}
        />
      </Modal>
    </div>
  );
}
