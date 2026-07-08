import { DownloadOutlined } from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "antd";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  authAdminUsersPartialUpdate,
  authAdminUsersResendInvitationCreate,
} from "@shared/api/generated/auth/auth";
import {
  commissioningResellersCreate,
  commissioningResellersDestroy,
  commissioningResellersPartialUpdate,
  getCommissioningResellersListQueryKey,
  useCommissioningResellersList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningResellersListParams,
  Reseller,
} from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { ROLES } from "@shared/auth/roles";
import { InviteUserModal, UserInfoModal } from "@shared/modals";
import { ExportCsv } from "@features/commissioning/modals";
import { ResellerInvoiceSettingsModal } from "@features/commissioning/modals/ResellerInvoiceSettingsModal";
import {
  EditableTable,
  type CrudResource,
  permissionsWithDeletable,
  useCrudListPage,
} from "@shared/tables";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import {
  DownloadCsvTemplateButton,
  ExplainerText,
  HideInactiveSwitch,
  LinkButton,
  StatusButton,
} from "@shared/ui";
import {
  useContactColumns,
  useNoteColumn,
  useTenant,
  useUserInfoModal,
} from "@hooks/index";
import { useOfferGroups } from "@features/commissioning/hooks";
import { isFieldDisabled, notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";

const RESELLER_LIST_PARAMS: CommissioningResellersListParams = {
  is_reseller: true,
};

// Typed on TableRecord (not Reseller & TableRecord): this page's columns +
// customEdit are TableRecord-typed. The create/update/delete casts sit here.
const resellersResource: CrudResource<TableRecord> = {
  useList: useCommissioningResellersList,
  create: (payload) =>
    commissioningResellersCreate(payload as unknown as Reseller),
  update: (id, payload) =>
    commissioningResellersPartialUpdate(id, payload as unknown as Reseller),
  delete: (id) =>
    commissioningResellersDestroy(id, { delete_context: "resellers" }),
  getListQueryKey: getCommissioningResellersListQueryKey,
};

export default function ListResellers() {
  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const { getSetting } = useTenant();
  const { noteColumn } = useNoteColumn();
  const queryClient = useQueryClient();
  const permissions = useMemo(
    () => permissionsWithDeletable(isOffice),
    [isOffice],
  );

  const [csvModalVisible, setCsvModalVisible] = useState(false);
  const [invoiceDrawerReseller, setInvoiceDrawerReseller] =
    useState<Reseller | null>(null);
  const [inviteForReseller, setInviteForReseller] =
    useState<TableRecord | null>(null);

  const uploadAllowed =
    (getSetting("allow_upload_for_data_lists", false) as boolean) === true;

  // Tenant-level defaults for the per-reseller payment-condition columns —
  // customEdit pre-fills these on new rows.
  const defaultPaymentTermsDays =
    (getSetting("payment_terms_reseller_in_days") as number | undefined) ?? 14;
  const defaultEarlyPaymentDiscountPercent = getSetting(
    "early_payment_discount_percent",
  ) as number | null | undefined;
  const defaultEarlyPaymentDiscountDays = getSetting(
    "early_payment_discount_days",
  ) as number | null | undefined;

  const list = useCrudListPage<TableRecord>({
    resource: resellersResource,
    permissions,
    activeField: "is_active_reseller",
    listParams: RESELLER_LIST_PARAMS,
  });

  const contactColumns = useContactColumns({
    translationPrefix: "resellers",
    overrides: {
      companyName: { disabled: isFieldDisabled },
      firstName: { disabled: isFieldDisabled },
      lastName: { disabled: isFieldDisabled },
      address: { inputType: "text", required: true, disabled: isFieldDisabled },
      zipCode: { inputType: "text", required: true, disabled: isFieldDisabled },
      city: { inputType: "text", required: true, disabled: isFieldDisabled },
    },
  });

  const { offerGroups, offerGroupsCount, defaultOfferGroupId } =
    useOfferGroups();
  const hasDifferentOfferGroups = offerGroupsCount > 0;

  const {
    isUserInfoModalOpen,
    selectedUserRecord,
    handleOpenUserInfoModal,
    handleCloseUserInfoModal,
    getUserStatus,
    getUserStatusSorter,
  } = useUserInfoModal();

  // Patch a single reseller row directly in the query cache. Avoids a full
  // re-fetch (which would re-sort/re-filter the table and lose scroll). Targets
  // the params-scoped key the list hook populated.
  const patchRowById = useCallback(
    (id: unknown, patch: Record<string, unknown>) => {
      queryClient.setQueryData(
        getCommissioningResellersListQueryKey(RESELLER_LIST_PARAMS),
        (old: unknown) =>
          Array.isArray(old)
            ? old.map((row) =>
                (row as TableRecord).id === id ? { ...row, ...patch } : row,
              )
            : old,
      );
    },
    [queryClient],
  );

  const handleSendInvitation = useCallback(
    (record: Record<string, unknown>) => {
      handleCloseUserInfoModal();
      setInviteForReseller(record as TableRecord);
    },
    [handleCloseUserInfoModal],
  );

  const handleResendInvitation = useCallback(
    async (record: Record<string, unknown>) => {
      const info = (record as TableRecord).linked_user_info as
        | { id?: string }
        | undefined;
      if (!info?.id) return;
      try {
        const updatedUser = await authAdminUsersResendInvitationCreate(info.id);
        notify.success(t("users.invitation_resent"));
        handleCloseUserInfoModal();
        // Patch only this row so we don't lose sort/scroll position.
        if (updatedUser) {
          patchRowById((record as TableRecord).id, {
            linked_user_info: updatedUser,
          });
        }
      } catch (error) {
        console.error("Operation failed:", error);
        notify.error(t("users.resend_failed"));
      }
    },
    [t, handleCloseUserInfoModal, patchRowById],
  );

  const setActive = useCallback(
    async (record: Record<string, unknown>, next: "active" | "inactive") => {
      const info = (record as TableRecord).linked_user_info as
        | { id?: string }
        | undefined;
      if (!info?.id) return;
      try {
        const updatedUser = await authAdminUsersPartialUpdate(info.id, {
          account_status: next,
        });
        notify.success(
          next === "inactive" ? t("users.deactivated") : t("users.activated"),
        );
        handleCloseUserInfoModal();
        patchRowById((record as TableRecord).id, {
          linked_user_info: updatedUser,
        });
      } catch (err: unknown) {
        notify.error(getErrorMessage(err, t("users.toggle_active_failed")));
      }
    },
    [t, handleCloseUserInfoModal, patchRowById],
  );

  const handleActivateUser = useCallback(
    (record: Record<string, unknown>) => setActive(record, "active"),
    [setActive],
  );
  const handleDeactivateUser = useCallback(
    (record: Record<string, unknown>) => setActive(record, "inactive"),
    [setActive],
  );

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => ({
      ...transformedData,
      is_reseller: true,
      comes_from_reseller_page: true,
    }),
    [],
  );

  const customEdit = useCallback(
    (
      record: TableRecord,
      form: { setFieldsValue: (values: Record<string, unknown>) => void },
    ) => {
      if (record.key === -1) {
        const defaultValues: Record<string, unknown> = {
          is_active_reseller: true,
          // Pre-fill payment conditions from the tenant defaults so the office
          // only edits these for resellers with custom terms.
          payment_terms_in_days: defaultPaymentTermsDays,
          early_payment_discount_percent: defaultEarlyPaymentDiscountPercent,
          early_payment_discount_days: defaultEarlyPaymentDiscountDays,
        };
        // Pre-select the protected default offer group for new resellers.
        if (defaultOfferGroupId) {
          defaultValues.offer_group_name = defaultOfferGroupId;
          defaultValues.offer_group = defaultOfferGroupId;
        }
        form.setFieldsValue(defaultValues);
        return { ...record, ...defaultValues };
      }
      return record;
    },
    [
      defaultPaymentTermsDays,
      defaultEarlyPaymentDiscountPercent,
      defaultEarlyPaymentDiscountDays,
      defaultOfferGroupId,
    ],
  );

  const columns = useMemo<EditableColumnConfig<TableRecord>[]>(
    () => [
      {
        title: <div className="checkbox-column-title">Link</div>,
        dataIndex: "link",
        key: "link",
        align: "center",
        disabled: true,
        width: "4em",
        render: (_: unknown, record: TableRecord) => (
          <LinkButton
            variant="view"
            to={`/commissioning/customer-orders/${record.id}`}
            tooltip={t("resellers.go_to_orders")}
          />
        ),
      },
      {
        // Per-row entry-point to ResellerInvoiceSettingsModal.
        title: "",
        dataIndex: "invoice_settings",
        key: "invoice_settings",
        align: "center",
        disabled: true,
        width: "10em",
        render: (_: unknown, record: TableRecord) => {
          const isUnsavedNewRow = record.key === -1 || !record.id;
          if (isUnsavedNewRow) return null;
          return (
            <Button
              size="small"
              type="primary"
              style={{
                backgroundColor: "var(--color-primary-hover)",
                borderColor: "var(--color-primary-hover)",
              }}
              onClick={() =>
                setInvoiceDrawerReseller(record as unknown as Reseller)
              }
            >
              {t("resellers.invoice_settings_title")}
            </Button>
          );
        },
      },
      {
        title: <>{t("resellers.is_active")}</>,
        dataIndex: "is_active_reseller",
        key: "is_active_reseller",
        inputType: "checkbox",
        required: false,
        sortable: true,
      },
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
        render: (_: unknown, record: TableRecord) => {
          const status = getUserStatus(record);
          return (
            <StatusButton
              variant={status.variant}
              onClick={() => handleOpenUserInfoModal(record)}
              tooltip={t(`users.${status.key}`)}
            />
          );
        },
        sorter: getUserStatusSorter,
      },
      {
        title: <>{t("resellers.is_also_delivery_station")}</>,
        dataIndex: "is_also_delivery_station",
        key: "is_also_delivery_station",
        inputType: "checkbox",
        required: false,
        sortable: true,
        // Disable unticking when the linked DS has dependants and can't be deleted.
        disabled: (record: TableRecord) =>
          !!record.is_also_delivery_station &&
          record.linked_delivery_station_can_be_deleted === false,
      },
      {
        title: <>{t("resellers.is_seller")}</>,
        dataIndex: "is_seller",
        key: "is_seller",
        inputType: "checkbox",
        required: false,
        sortable: true,
      },
      contactColumns.companyName,
      contactColumns.firstName,
      contactColumns.lastName,
      contactColumns.address,
      contactColumns.zipCode,
      contactColumns.city,
      contactColumns.email,
      contactColumns.phone,
      contactColumns.phone2,
      ...(hasDifferentOfferGroups
        ? ([
            {
              title: <>{t("resellers.offer_group")}</>,
              dataIndex: "offer_group_name",
              key: "offer_group",
              inputType: "select",
              required: false,
              width: "12em",
              options: offerGroups,
              sortable: true,
              foreignKey: {
                valueField: "offer_group",
                displayField: "offer_group_name",
              },
            },
          ] as EditableColumnConfig<TableRecord>[])
        : []),
      {
        title: <>{t("resellers.offer_via_email")}</>,
        dataIndex: "offer_via_email",
        key: "offer_via_email",
        inputType: "checkbox",
        required: false,
      },
      {
        title: <>{t("resellers.delivery_note_via_email")}</>,
        dataIndex: "delivery_note_via_email",
        key: "delivery_note_via_email",
        inputType: "checkbox",
        required: false,
      },
      {
        ...noteColumn,
        inputType: "optional",
        width: "25em",
      },
    ],
    [
      contactColumns,
      getUserStatus,
      getUserStatusSorter,
      handleOpenUserInfoModal,
      hasDifferentOfferGroups,
      noteColumn,
      offerGroups,
      t,
    ],
  );

  return (
    <div>
      <div className="flex-between">
        <h1>{t("resellers.list_resellers")}</h1>
        <Button
          className="download-button"
          icon={<DownloadOutlined />}
          onClick={() => setCsvModalVisible(true)}
        >
          {t("commissioning.csv_export_resellers")}
        </Button>
      </div>

      <HideInactiveSwitch
        value={list.hideInactive}
        onChange={list.setHideInactive}
      />

      <EditableTable
        columns={columns}
        apiFunctions={list.apiFunctions}
        initialData={list.filteredData}
        loading={list.isLoading}
        onSaveSuccess={list.onSaveSuccess}
        onDeleteSuccess={list.onDeleteSuccess}
        customSave={customSave}
        customEdit={customEdit}
        deleteContext={"resellers"}
        permissions={list.permissions}
        pagination={true}
        showSearchBar={true}
      />

      <UserInfoModal
        isOpen={isUserInfoModalOpen}
        onClose={handleCloseUserInfoModal}
        record={selectedUserRecord}
        onSendInvitation={handleSendInvitation}
        onResendInvitation={handleResendInvitation}
        onActivateUser={handleActivateUser}
        onDeactivateUser={handleDeactivateUser}
      />

      <InviteUserModal
        open={!!inviteForReseller}
        onClose={() => setInviteForReseller(null)}
        onCreated={() => {
          setInviteForReseller(null);
          list.invalidate();
        }}
        title={t("users.invite_title")}
        defaultRoles={[ROLES.CUSTOMER]}
        lockedRoles={[ROLES.CUSTOMER]}
        allowedRoles={[ROLES.CUSTOMER]}
        initialValues={
          inviteForReseller
            ? {
                first_name:
                  (inviteForReseller.first_name as string | undefined) ?? "",
                last_name:
                  (inviteForReseller.last_name as string | undefined) ?? "",
                email: (inviteForReseller.email as string | undefined) ?? "",
                reseller_id:
                  (inviteForReseller.id as string | undefined) ?? null,
              }
            : undefined
        }
      />
      <ExportCsv
        open={csvModalVisible}
        onClose={() => setCsvModalVisible(false)}
        columns={
          columns as unknown as Parameters<typeof ExportCsv>[0]["columns"]
        }
        data={list.data}
        filename={t("resellers.list_resellers")}
      />
      <ExplainerText title={t("common.info")}>
        {t("explainers.list_resellers")}
      </ExplainerText>

      {uploadAllowed && (
        <DownloadCsvTemplateButton
          columns={columns}
          filename={t("commissioning.resellers_template.csv")}
          modelName="reseller"
          onUploadSuccess={list.invalidate}
        />
      )}

      <ResellerInvoiceSettingsModal
        open={!!invoiceDrawerReseller}
        reseller={invoiceDrawerReseller}
        onClose={() => setInvoiceDrawerReseller(null)}
        onSaved={(updated: Reseller) => {
          // Patch the matching row in the cache so the table doesn't need a
          // full refetch — keeps scroll position + search intact.
          patchRowById(
            updated.id,
            updated as unknown as Record<string, unknown>,
          );
        }}
      />
    </div>
  );
}
