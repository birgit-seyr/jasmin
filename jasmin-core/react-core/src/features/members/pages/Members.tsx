import { authAdminUsersPartialUpdate } from "@shared/api/generated/auth/auth";
import {
  commissioningMembersCreate,
  commissioningMembersDestroy,
  commissioningMembersPartialUpdate,
  commissioningMembersSendInvitationCreate,
  getCommissioningMembersListQueryKey,
  useCommissioningMembersList,
} from "@shared/api/generated/commissioning/commissioning";
import type { Member } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { ROLES } from "@shared/auth/roles";
import { useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Space } from "antd";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
// Imported directly from its source module (not the ``modals`` barrel) to
// avoid a Rollup chunk cycle: the barrel re-exports this modal while the
// modal transitively depends back on the barrel (via the ``hooks`` barrel).
import { useAdminConfirmationModalMembers } from "@features/members/hooks/modals/useAdminConfirmationModalMembers";
import { useRejectMemberModal } from "@features/members/hooks/modals/useRejectMemberModal";
import {
  CancelMembershipModal,
  CoopSharesModal,
  MemberBankDetailsModal,
  MemberEmailsModal,
} from "@features/members/modals";
import { AdminConfirmationModalMembers } from "@features/members/modals/AdminConfirmationModalMembers";
import ExportCsvMemberRegister from "@features/members/modals/ExportCsvMemberRegister";
import { RejectMemberModal } from "@features/members/modals/RejectMemberModal";
import {
  useContactColumns,
  useDateFormat,
  useInvalidateAfterTableMutation,
  useNoteColumn,
  useTableRowSelection,
  useTenant,
  useUserInfoModal,
} from "@hooks/index";
import { InviteUserModal, LoggingModal, UserInfoModal } from "@shared/modals";
import {
  adminConfirmationColumn,
  EditableTable,
  gatedByPermission,
  wrapApiFunctions,
} from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import {
  DownloadCsvTemplateButton,
  ExplainerText,
  LinkButton,
  StatusButton,
  ToolTipIcon,
} from "@shared/ui";
import MemberStatsCards from "@features/members/components/MemberStatsCards";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import type { MemberRecord } from "./types";

export default function Members() {
  const queryClient = useQueryClient();

  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const permissions = useMemo(
    () => ({
      ...gatedByPermission(isOffice),
      // Deletable only while pending review: not confirmed, not yet REJECTED
      // (a rejected applicant's row is kept for statistics), and server says so.
      canDeleteRecord: (record: MemberRecord) =>
        !record.admin_confirmed &&
        !record.admin_rejected_at &&
        !!record.can_be_deleted,
    }),
    [isOffice],
  );
  const { tenant, getSetting } = useTenant();
  const uploadAllowed =
    getSetting("allow_upload_for_data_lists", false) === true;

  const defaultCountry = tenant?.country || "DE";

  const contactColumns = useContactColumns({
    translationPrefix: "members",
    overrides: {
      // ``col-member-name`` lets the row-state CSS tint these cells: dark green
      // for members with active subscriptions (``member-row--has-active-subs``).
      firstName: {
        required: true,
        fixed: true,
        width: "12em",
        className: "col-member-name",
      },
      lastName: {
        required: true,
        fixed: true,
        width: "12em",
        className: "col-member-name",
      },
    },
  });

  const { formatDate } = useDateFormat();
  const { noteColumn } = useNoteColumn({ inputType: "optional" });

  const {
    selectedRowKeys,
    onSelectedRowsChange: handleRowSelectionChange,
    rowSelection: rowSelectionConfig,
  } = useTableRowSelection(
    (record: TableRecord) => record.key === -1 || Boolean(record.is_approved),
  );
  const [loggingModalOpen, setLoggingModalOpen] = useState(false);
  const [loggingRecord, setLoggingRecord] = useState<MemberRecord | null>(null);
  const [exportCsvVisible, setExportCsvVisible] = useState(false);
  const [emailsRecord, setEmailsRecord] = useState<MemberRecord | null>(null);
  const [cancelRecord, setCancelRecord] = useState<MemberRecord | null>(null);
  const [bankRecord, setBankRecord] = useState<MemberRecord | null>(null);
  const [coopSharesRecord, setCoopSharesRecord] = useState<MemberRecord | null>(
    null,
  );
  const [inviteRow, setInviteRow] = useState<MemberRecord | null>(null);

  // Capture as a primitive so the columns useMemo can depend on a
  // stable boolean instead of ``getSetting`` itself, which is a fresh
  // function every TenantContext render — listing ``getSetting`` in
  // the deps would rebuild ``columns`` on every render, hand
  // EditableTable a new ``columns`` reference, and wipe its internal
  // add-row state (symptom: just-saved rows disappear until full page
  // refresh).
  const has_coop_shares = !!getSetting("has_coop_shares", true);

  // Trial-member column visibility is derived: the concept only exists
  // when trial subs are enabled AND trial subs are allowed for trial
  // members (the only thing a trial member does). The standalone
  // ``allows_trial_members`` flag was dropped in migration 0020.
  const allows_trial_members =
    !!getSetting("allows_trial_subscriptions", true) &&
    !!getSetting("allows_trial_subscriptions_for_trial_members", true);

  // Fields that become legally fixed once a Member is admin-confirmed
  // (Mitglied der Genossenschaft per GenG): ``birth_date`` (biological
  // fact + GDPR-classified PII whose audit trail edits would falsify)
  // and ``is_trial`` (the trial → full conversion is one-way; flipping
  // back would orphan the assigned Mitgliedsnummer / Eintrittsdatum).
  // The Member serializer enforces the same lock server-side; this UI
  // predicate is a usability hint, not the security boundary.
  const lockedAfterAdminConfirmation = (record: MemberRecord) =>
    !!record.admin_confirmed;

  const {
    isUserInfoModalOpen,
    selectedUserRecord,
    handleOpenUserInfoModal,
    handleCloseUserInfoModal,
    getUserStatus,
    getUserStatusSorter,
  } = useUserInfoModal();

  const {
    isAdminConfirmationModalOpen,
    selectedMemberForConfirmation,
    loading: adminModalLoading,
    handleOpenAdminConfirmationModal,
    handleCloseAdminConfirmationModal,
    confirmMember,
    getAdminStatus,
    getAdminStatusSorter,
  } = useAdminConfirmationModalMembers();

  const {
    isRejectModalOpen,
    selectedMemberForRejection,
    loading: rejectModalLoading,
    reason: rejectionReason,
    setReason: setRejectionReason,
    handleOpenRejectModal,
    handleCloseRejectModal,
    rejectMember,
  } = useRejectMemberModal();

  const { data: rawData, isLoading } = useCommissioningMembersList();
  // ONE directional boundary cast: the generated ``Member`` rows lack the
  // table-only ``key`` / index-signature surface EditableTable requires.
  // Everything downstream reads the checked ``MemberRecord`` fields.
  const data = useMemo(
    () => (rawData ?? []) as unknown as MemberRecord[],
    [rawData],
  );

  // "Needs attention" quick filter, toggled by the page badges below: "members"
  // (awaiting admin confirmation) or "coop" (has coop shares awaiting
  // confirmation). Filters the loaded rows client-side; toggling the active
  // badge off restores the full list.
  const [attentionFilter, setAttentionFilter] = useState<
    "members" | "coop" | null
  >(null);
  const pendingMembersCount = useMemo(
    () =>
      data.filter(
        (record) => !record.admin_confirmed && !record.admin_rejected_at,
      ).length,
    [data],
  );
  const pendingCoopCount = useMemo(
    () =>
      data.filter((record) => Number(record.coop_shares_pending_count ?? 0) > 0)
        .length,
    [data],
  );
  const displayData = useMemo(() => {
    if (attentionFilter === "members") {
      return data.filter(
        (record) => !record.admin_confirmed && !record.admin_rejected_at,
      );
    }
    if (attentionFilter === "coop") {
      return data.filter(
        (record) => Number(record.coop_shares_pending_count ?? 0) > 0,
      );
    }
    return data;
  }, [data, attentionFilter]);

  // Total Einlagen (coop-share equity) across the rows currently in
  // view. Only shown when the tenant has coop shares enabled — for
  // tenants without ``has_coop_shares`` the equity column is hidden
  // and the total would be meaningless.
  const totalCoopShares = useMemo(
    () =>
      data.reduce(
        (sum, record) => sum + (Number(record.coop_shares_total) || 0),
        0,
      ),
    [data],
  );


  // No ``list`` here: this page owns the data via ``useCommissioningMembersList``
  // and passes it as ``initialData``. Adding ``list`` would make EditableTable
  // also auto-fetch (it does when ``showSearchBar`` + ``apiFunctions.list`` are
  // both set), double-fetching the same endpoint. Search filters client-side;
  // mutations refresh via the ``onSaveSuccess``/``onDeleteSuccess`` invalidation.
  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<Member & TableRecord>({
        create: (data) => commissioningMembersCreate(data),
        update: (id, data) => commissioningMembersPartialUpdate(id, data),
        delete: (id) => commissioningMembersDestroy(id),
      }),
    [],
  );

  const customEdit = useCallback(
    (
      record: MemberRecord,
      form: { setFieldsValue: (v: Record<string, unknown>) => void },
    ) => {
      if (record.key === -1) {
        const defaultValues = { country: defaultCountry };
        form.setFieldsValue(defaultValues);
        return { ...record, ...defaultValues };
      }
      return record;
    },
    [defaultCountry],
  );

  const columns: EditableColumnConfig<MemberRecord>[] = useMemo(
    () => [
      {
        title: <div className="checkbox-column-title">Link</div>,
        dataIndex: "link",
        key: "link",
        align: "center",
        disabled: true,
        width: "4em",
        render: (_: unknown, record: MemberRecord) => (
          <LinkButton
            variant="view"
            to={`/members/members/${record.id}`}
            tooltip={t("members.view_details")}
          />
        ),
      },
      adminConfirmationColumn<MemberRecord>({
        t,
        getAdminStatus,
        onOpen: handleOpenAdminConfirmationModal,
        sorter: getAdminStatusSorter,
      }),
      {
        title: (
          <div className="checkbox-column-title">
            {t("members.user_status")}
          </div>
        ),
        dataIndex: "user_status",
        key: "user_status",
        align: "center",
        width: "4em",
        disabled: true,
        render: (_: unknown, record: MemberRecord) => {
          const status = getUserStatus(record);
          return (
            <StatusButton
              variant={status.variant}
              onClick={() => handleOpenUserInfoModal(record)}
            />
          );
        },
        sorter: getUserStatusSorter,
        showSorterTooltip: false,
      },
      {
        title: (
          <>
            {t("members.member_number")}
            <ToolTipIcon title={t("tooltip.member_number")} />
          </>
        ),
        dataIndex: "member_number",
        key: "member_number",
        inputType: "positive_integer",
        required: false,
        readOnly: true,
        fixed: true,
        align: "center",
        width: "4em",
        sortable: true,
        render: (value: unknown, record: MemberRecord) => {
          const display =
            record.is_trial && !value ? (
              <span
                style={{
                  fontSize: "0.85em",
                  color: "var(--color-text-muted)",
                  fontStyle: "italic",
                }}
              >
                {t("commissioning.trial_member")}
              </span>
            ) : (
              (value as number) || ""
            );
          // Cancelled members: the struck-through row signals the exit; the exit
          // date (GenG §30 Austrittsdatum) is on hover over the member number.
          if (record.cancelled_at) {
            return (
              <span
                title={t("members.member_cancelled_title", {
                  date: formatDate(record.cancelled_effective_at ?? null),
                })}
              >
                {display}
              </span>
            );
          }
          return display;
        },
      },
      ...(allows_trial_members
        ? ([
            {
              title: <>{t("members.is_trial")}</>,
              dataIndex: "is_trial",
              key: "is_trial",
              inputType: "checkbox",
              required: false,
              align: "center",
              sortable: true,
              className: "is-trial-checkbox",
              // Trial → full conversion is one-way under the model:
              // ``trial_converted_at`` stamps the moment, and
              // ``member_number`` + ``entry_date`` get assigned
              // together. Flipping ``is_trial`` back to True on a
              // confirmed member would falsify the Mitgliederliste
              // and orphan the assigned Mitgliedsnummer. The
              // serializer enforces the same lock server-side, so
              // this UI gate is a usability hint, not the security
              // boundary.
              disabled: lockedAfterAdminConfirmation,
              render: (value: unknown) => (value ? "✓" : ""),
            },
          ] as EditableColumnConfig<MemberRecord>[])
        : []),
      {
        // GenG §30 Eintrittsdatum — the date the Vorstand admitted
        // the member into the Mitgliederliste. Stamped server-side
        // in ``_post_confirm`` (full members) or in the trial-
        // conversion hook on first CoopShare. Not an office-chosen
        // value, NOT the share-payment date — same readOnly
        // treatment as ``member_number``. Historical correction for
        // migrated members happens via direct DB / data migration.
        title: (
          <>
            {t("members.entry_date")}
            <ToolTipIcon title={t("tooltip.entry_date")} />
          </>
        ),
        dataIndex: "entry_date",
        key: "entry_date",
        inputType: "date",
        required: false,
        readOnly: false,
        align: "center",
        width: "8em",
        disabled: true,
        sortable: true,

        render: (value: unknown) => formatDate(value as string | null),
      },
      {
        title: <>{t("members.cancelled_effective_at_date")}</>,
        dataIndex: "cancelled_effective_at",
        key: "cancelled_effective_at",
        inputType: "date",
        required: false,
        readOnly: true,
        align: "center",
        width: "8em",
        sortable: true,

        render: (value: unknown) => formatDate(value as string | null),
      },
      ...(has_coop_shares
        ? ([
            {
              title: t("members.coop_shares"),
              dataIndex: "coop_shares_action",
              key: "coop_shares_action",
              width: "7em",
              align: "center",
              readOnly: true,
              disabled: true,
              // Sort by share count so the office can quickly spot
              // non-trial members with no equity. Pin placeholder (-1)
              // row to top regardless of direction.
              sorter: (
                a: MemberRecord,
                b: MemberRecord,
                sortOrder?: "ascend" | "descend",
              ) => {
                if (a.key === -1) return sortOrder === "descend" ? 1 : -1;
                if (b.key === -1) return sortOrder === "descend" ? -1 : 1;
                // ``coop_shares_total`` is a decimal STRING on the wire.
                return (
                  Number(a.coop_shares_total ?? 0) -
                  Number(b.coop_shares_total ?? 0)
                );
              },
              render: (_: unknown, record: MemberRecord) => {
                if (record.key === -1) return null;
                const total = Number(record.coop_shares_total ?? 0);
                const violatesMinEquity = !record.is_trial && total === 0;
                // Red when a non-trial member has no shares — same
                // invariant the backend ``MemberCoopSharesOutOfRange``
                // enforces at confirm-time. Office spots it from the
                // list without opening the modal.
                const color = violatesMinEquity
                  ? "var(--color-error, #c0392b)"
                  : undefined;
                return (
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                      color,
                      fontWeight: violatesMinEquity ? 600 : undefined,
                    }}
                  >
                    <span>{total}</span>
                    <Badge
                      count={Number(record.coop_shares_pending_count ?? 0)}
                      size="small"
                      color="gold"
                      title={t("members.coop_shares_awaiting_confirmation", {
                        count: Number(record.coop_shares_pending_count ?? 0),
                      })}
                    >
                      <StatusButton
                        variant={
                          violatesMinEquity ? "coopsharesAlert" : "coopshares"
                        }
                        onClick={() => setCoopSharesRecord(record)}
                        tooltip={t("members.coop_shares")}
                      />
                    </Badge>
                  </span>
                );
              },
            },
          ] as EditableColumnConfig<MemberRecord>[])
        : []),

      contactColumns.firstName,
      contactColumns.lastName,
      contactColumns.companyName,
      contactColumns.email,
      contactColumns.address,
      contactColumns.zipCode,
      contactColumns.city,
      contactColumns.country,
      {
        // After admin confirmation, ``birth_date`` is fixed reality
        // and edits would falsify the GDPR-classified PII audit
        // trail. The serializer rejects the same edits server-side;
        // this UI lock is a usability hint, not the security
        // boundary. Typo corrections after confirmation need ops
        // intervention (DB / data migration).
        title: <>{t("members.birth_date")}</>,
        dataIndex: "birth_date",
        key: "birth_date",
        inputType: "date",
        required: false,
        align: "center",
        width: "8em",
        sortable: true,
        disabled: lockedAfterAdminConfirmation,
        render: (value: unknown) => formatDate(value as string | null),
      },
      {
        title: <>{t("members.is_student")}</>,
        dataIndex: "is_student",
        key: "is_student",
        inputType: "checkbox",
        required: false,
        align: "center",
        width: "8em",
        disabled: (record: MemberRecord) => Boolean(record.is_trial),
      },
      {
        title: <>{t("members.account_owner")}</>,
        // Decrypted bank data is never echoed in the bulk grid — the office
        // serializer returns only a masked representation. ``readOnly`` also
        // keeps the field out of the row save payload, so editing an
        // unrelated cell can't blank the stored value. Full editing happens
        // on the dedicated SEPA surface, not inline here.
        dataIndex: "account_owner_masked",
        key: "account_owner_masked",
        readOnly: true,
        width: "14em",
        align: "left",
      },
      {
        title: <>{t("members.iban")}</>,
        dataIndex: "iban_masked",
        key: "iban_masked",
        readOnly: true,
        width: "16em",
        align: "left",
      },
      noteColumn,
      {
        title: "",
        dataIndex: "emails",
        key: "emails",
        width: "3em",
        align: "center",
        readOnly: true,
        disabled: true,
        render: (_: unknown, record: MemberRecord) => {
          if (record.key === -1) return null;
          return (
            <StatusButton
              variant="emails"
              onClick={() => setEmailsRecord(record)}
              tooltip={t("members.sent_emails")}
            />
          );
        },
      },
      {
        title: "",
        dataIndex: "logging",
        key: "logging",
        width: "3em",
        align: "center",
        readOnly: true,
        disabled: true,
        render: (_: unknown, record: MemberRecord) => {
          if (record.key === -1) return null;
          return (
            <StatusButton
              variant="logging"
              onClick={() => {
                setLoggingRecord(record);
                setLoggingModalOpen(true);
              }}
              tooltip={t("logging.title")}
            />
          );
        },
      },
      {
        title: "",
        dataIndex: "bank_details",
        key: "bank_details",
        width: "3em",
        align: "center",
        readOnly: true,
        disabled: true,
        render: (_: unknown, record: MemberRecord) => {
          // Office edit of the member's stored bank details (Member.iban /
          // account_owner). The grid shows only the masked companions, so the
          // full value is set here — works for members with no linked user
          // (who can't self-edit via MyDataTab). Placeholder rows excluded.
          if (record.key === -1) return null;
          return (
            <StatusButton
              variant="bankDetails"
              onClick={() => setBankRecord(record)}
              tooltip={t("members.edit_bank_details")}
            />
          );
        },
      },
      {
        title: "",
        dataIndex: "cancel",
        key: "cancel",
        width: "3em",
        align: "center",
        readOnly: true,
        disabled: true,
        render: (_: unknown, record: MemberRecord) => {
          // Office-cancel a membership. Only confirmed, not-yet-cancelled
          // members; placeholder rows excluded. Force-cancel — cascades to
          // coop shares + ends subscriptions server-side.
          if (record.key === -1) return null;
          if (!record.admin_confirmed) return null;
          if (record.cancelled_at) return null;
          return (
            <StatusButton
              variant="cancel"
              onClick={() => setCancelRecord(record)}
              tooltip={t("members.cancel_membership_button_tooltip")}
            />
          );
        },
      },
    ],
    [
      t,
      handleOpenAdminConfirmationModal,
      handleOpenUserInfoModal,
      getAdminStatus,
      getAdminStatusSorter,
      getUserStatus,
      getUserStatusSorter,
      allows_trial_members,
      formatDate,
      contactColumns,
      noteColumn,
      has_coop_shares,
    ],
  );

  const handleDataChange = useCallback(() => {
    // exact:true — this page mounts only the paramless members-list key.
    // Without it, prefix-matching also invalidates the params-bearing
    // useMembers() variants other screens use (member dropdowns/selectors),
    // which is needless work.
    queryClient.invalidateQueries({
      queryKey: getCommissioningMembersListQueryKey(),
      exact: true,
    });
  }, [queryClient]);

  // Stop reorder-on-save — see ``useInvalidateAfterTableMutation``
  // docstring. ``handleDataChange`` is still used as the CSV upload's
  // ``onUploadSuccess`` (line ~604) where a refetch IS wanted; this
  // hook only swaps it out for the inline-edit save path.
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(handleDataChange);

  // Patch a single row in the cached list. Avoids re-fetching (which
  // would re-sort/re-page the table). ``patch`` is shallow-merged into
  // the matching row.
  const patchRowById = useCallback(
    (id: unknown, patch: Record<string, unknown>) => {
      queryClient.setQueriesData<unknown>(
        { queryKey: getCommissioningMembersListQueryKey() },
        (old: unknown) => {
          if (!Array.isArray(old)) return old;
          return old.map((row: any) =>
            row && row.id === id ? { ...row, ...patch } : row,
          );
        },
      );
    },
    [queryClient],
  );

  // ---- Activate / deactivate the linked user account -------------------
  // Structural param: covers both the member row and the record shape the
  // UserInfoModal callbacks hand back (which is the same row, structurally).
  const setUserActive = useCallback(
    async (
      record: {
        id?: string | number;
        linked_user_info?: { id?: string } | null;
      },
      next: "active" | "inactive",
    ) => {
      const info = record.linked_user_info;
      if (!info?.id) return;
      try {
        const updatedUser = await authAdminUsersPartialUpdate(info.id, {
          account_status: next,
        });
        notify.success(
          next === "inactive" ? t("users.deactivated") : t("users.activated"),
        );
        // Patch only this member's row — don't re-fetch / re-sort the table.
        patchRowById(record.id, {
          linked_user_info: updatedUser,
        });
        handleCloseUserInfoModal();
      } catch (err: unknown) {
        notify.error(getErrorMessage(err, t("users.toggle_active_failed")));
      }
    },
    [t, handleCloseUserInfoModal, patchRowById],
  );

  return (
    <div>
      <h1>{t("members.list_members")}</h1>

      <div className="members-list-toolbar">
        <MemberStatsCards
          fallbackMemberCount={data.length}
          fallbackCoopShares={totalCoopShares}
        />
        {isOffice && (
          <Button
            onClick={() => setExportCsvVisible(true)}
            className="download-button"
          >
            {t("members.export_member_register")}
          </Button>
        )}
      </div>

      {(pendingMembersCount > 0 ||
        (has_coop_shares && pendingCoopCount > 0)) && (
        <Space style={{ marginBottom: 12 }} size="large" wrap>
          {pendingMembersCount > 0 && (
            <Badge count={pendingMembersCount} size="small">
              <Button
                size="small"
                type={attentionFilter === "members" ? "primary" : "default"}
                onClick={() =>
                  setAttentionFilter((prev) =>
                    prev === "members" ? null : "members",
                  )
                }
              >
                {t("members.attention_chip_members")}
              </Button>
            </Badge>
          )}
          {has_coop_shares && pendingCoopCount > 0 && (
            <Badge count={pendingCoopCount} size="small" color="gold">
              <Button
                size="small"
                type={attentionFilter === "coop" ? "primary" : "default"}
                onClick={() =>
                  setAttentionFilter((prev) =>
                    prev === "coop" ? null : "coop",
                  )
                }
              >
                {t("members.attention_chip_coop")}
              </Button>
            </Badge>
          )}
        </Space>
      )}

      <EditableTable
        columns={columns}
        apiFunctions={apiFunctions}
        focusIndex="first_name"
        initialData={displayData}
        loading={isLoading}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        customEdit={customEdit}
        uniqueCheck={["member_number"]}
        uniqueCheckMessage={t(
          "validation.unique.members_member_number_must_be_unique",
        )}
        permissions={permissions}
        pagination={true}
        showSearchBar={true}
        rowSelection={rowSelectionConfig}
        onSelectedRowsChange={handleRowSelectionChange}
        selectedRowKeys={selectedRowKeys}
        rowClassName={(record) => {
          // Cancelled wins (terminal): struck-through + muted. Otherwise tint
          // the name cells dark green when the member holds active subscriptions.
          if (record.cancelled_at) return "member-row--cancelled";
          if ((record.active_subscriptions_count ?? 0) > 0) {
            return "member-row--has-active-subs";
          }
          return "";
        }}
      />

      <AdminConfirmationModalMembers
        isOpen={isAdminConfirmationModalOpen}
        onClose={handleCloseAdminConfirmationModal}
        member={selectedMemberForConfirmation}
        onConfirm={async () => {
          const updated = await confirmMember();
          // Patch only the confirmed row so the table doesn't re-sort.
          const targetId = updated?.id ?? selectedMemberForConfirmation?.id;
          if (targetId !== undefined) {
            patchRowById(
              targetId,
              updated ? { ...updated } : { admin_confirmed: true },
            );
          }
        }}
        onReject={() => {
          // Hand the same member off to the reject modal. We close the
          // confirm modal first so the user only sees one modal at a
          // time.
          const target = selectedMemberForConfirmation;
          handleCloseAdminConfirmationModal();
          if (target) {
            handleOpenRejectModal(target);
          }
        }}
        loading={adminModalLoading}
      />

      <RejectMemberModal
        isOpen={isRejectModalOpen}
        onClose={handleCloseRejectModal}
        member={selectedMemberForRejection}
        reason={rejectionReason}
        onReasonChange={setRejectionReason}
        loading={rejectModalLoading}
        onReject={async () => {
          const targetId = selectedMemberForRejection?.id;
          const data = await rejectMember();
          // Patch the row with whatever fields the backend touched
          // (admin_confirmed stays false, cancelled_at gets stamped,
          // rejected_at if the model has it). Falls back to a minimal
          // shape so the row still updates if the API response is
          // sparse.
          if (targetId !== undefined) {
            patchRowById(
              targetId,
              data ? { ...data } : { admin_confirmed: false },
            );
          }
        }}
      />

      <UserInfoModal
        isOpen={isUserInfoModalOpen}
        onClose={handleCloseUserInfoModal}
        record={selectedUserRecord}
        onSendInvitation={(record) => {
          handleCloseUserInfoModal();
          // The modal hands back the row it was opened with, which on this
          // page is always the member row — reassert the member shape.
          setInviteRow(record as MemberRecord);
        }}
        onResendInvitation={(record) => {
          handleCloseUserInfoModal();
          setInviteRow(record as MemberRecord);
        }}
        onActivateUser={(record) => setUserActive(record, "active")}
        onDeactivateUser={(record) => setUserActive(record, "inactive")}
      />

      <ExportCsvMemberRegister
        open={exportCsvVisible}
        onClose={() => setExportCsvVisible(false)}
      />

      <LoggingModal
        isOpen={loggingModalOpen}
        onClose={() => {
          setLoggingModalOpen(false);
          setLoggingRecord(null);
        }}
        record={loggingRecord}
        title={`${t("logging.title")} - ${loggingRecord?.first_name || ""} ${loggingRecord?.last_name || ""}`}
      />

      <MemberEmailsModal
        isOpen={emailsRecord !== null}
        onClose={() => setEmailsRecord(null)}
        memberId={emailsRecord?.id ?? null}
        memberName={
          emailsRecord
            ? `${emailsRecord.first_name || ""} ${emailsRecord.last_name || ""}`.trim()
            : undefined
        }
      />

      <CoopSharesModal
        isOpen={coopSharesRecord !== null}
        onClose={() => setCoopSharesRecord(null)}
        memberId={coopSharesRecord?.id ?? null}
        memberName={
          coopSharesRecord
            ? `${coopSharesRecord.first_name || ""} ${coopSharesRecord.last_name || ""}`.trim()
            : undefined
        }
        isTrial={!!coopSharesRecord?.is_trial}
        adminConfirmed={!!coopSharesRecord?.admin_confirmed}
        memberCancelledEffectiveAt={
          coopSharesRecord?.cancelled_effective_at ?? null
        }
      />

      <CancelMembershipModal
        isOpen={cancelRecord !== null}
        onClose={() => setCancelRecord(null)}
        memberId={cancelRecord?.id ?? null}
        memberName={
          cancelRecord
            ? `${cancelRecord.first_name || ""} ${cancelRecord.last_name || ""}`.trim()
            : undefined
        }
        onCancelled={() => {
          patchRowById(cancelRecord?.id, {
            cancelled_at: new Date().toISOString(),
          });
          handleDataChange();
        }}
      />

      <MemberBankDetailsModal
        open={bankRecord !== null}
        memberId={bankRecord?.id ?? null}
        ibanMasked={bankRecord?.iban_masked}
        accountOwnerMasked={bankRecord?.account_owner_masked}
        onClose={() => setBankRecord(null)}
        onSaved={handleDataChange}
      />

      <ExplainerText title={t("common.info")}>
        {t("explainers.members")}
      </ExplainerText>

      {uploadAllowed && (
        <DownloadCsvTemplateButton
          columns={columns}
          filename={t("commissioning.members_template.csv")}
          modelName="member"
          onUploadSuccess={handleDataChange}
        />
      )}

      <InviteUserModal
        open={inviteRow !== null}
        onClose={() => setInviteRow(null)}
        title={t("members.send_invitation")}
        okText={t("commissioning.send")}
        defaultRoles={[ROLES.MEMBER]}
        lockedRoles={[ROLES.MEMBER]}
        allowedRoles={[ROLES.MEMBER]}
        submitFn={() =>
          // ``send_invitation`` takes no request body (request=None) —
          // the backend derives everything from the member row.
          commissioningMembersSendInvitationCreate(String(inviteRow?.id ?? "0"))
        }
        initialValues={{
          first_name: inviteRow?.first_name ?? "",
          last_name: inviteRow?.last_name ?? "",
          email: inviteRow?.email ?? "",
        }}
        onCreated={() => {
          notify.success(t("members.invitation_sent"));
          // exact:true — scope to this page's key (see handleDataChange above).
          queryClient.invalidateQueries({
            queryKey: getCommissioningMembersListQueryKey(),
            exact: true,
          });
        }}
      />
    </div>
  );
}
