import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
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
import {
  EditableTable,
  permissionsWithDeletable,
  wrapApiFunctions,
} from "@shared/tables";
import type {
  ApiFunctions,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import {
  ExplainerText,
  HideInactiveSwitch,
  ToolTipIcon,
  DownloadCsvTemplateButton,
} from "@shared/ui";
import {
  useContactColumns,
  useInvalidateAfterTableMutation,
  useTenant,
} from "@hooks/index";
import { isFieldDisabled } from "@shared/utils";

export default function ListSellers() {
  const { isOffice } = useRoles();
  const permissions = useMemo(
    () => permissionsWithDeletable(isOffice),
    [isOffice],
  );
  const [hideInactive, setHideInactive] = useState(true);
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const { getSetting } = useTenant();

  const uploadAllowed =
    (getSetting("allow_upload_for_data_lists", false) as boolean) === true;

  const contactColumns = useContactColumns({
    translationPrefix: "resellers",
    overrides: {
      companyName: { disabled: isFieldDisabled },
      firstName: { disabled: isFieldDisabled },
      lastName: { disabled: isFieldDisabled },
      address: { inputType: "text", required: true },
      zipCode: { inputType: "text", required: true },
      city: { inputType: "text", required: true },
    },
  });

  const listParams = useMemo<CommissioningResellersListParams>(
    () => ({ is_seller: true }),
    [],
  );

  // Page owns the data via ``useCommissioningResellersList`` (passed as
  // ``initialData``); no ``list`` in ``apiFunctions`` so the table never
  // double-fetches. Mutations refresh through the invalidation below.
  const { data: rawData, isLoading } = useCommissioningResellersList(listParams);
  const data = useMemo(
    () => (rawData ?? []) as unknown as TableRecord[],
    [rawData],
  );
  const filteredData = useMemo(
    () => (hideInactive ? data.filter((r) => r.is_active_seller) : data),
    [data, hideInactive],
  );
  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningResellersListQueryKey(listParams),
    });
  }, [queryClient, listParams]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<Reseller & TableRecord>({
        create: (payload) => commissioningResellersCreate(payload),
        update: (id, payload) =>
          commissioningResellersPartialUpdate(id, payload),
        delete: (id) =>
          commissioningResellersDestroy(id, { delete_context: "sellers" }),
      }),
    [],
  );

  const customSave = useCallback((transformedData: Record<string, unknown>) => {
    return {
      ...transformedData,
      is_seller: true,
      comes_from_seller_page: true,
    };
  }, []);

  const customEdit = useCallback(
    (
      record: TableRecord,
      form: { setFieldsValue: (values: Record<string, unknown>) => void },
    ) => {
      if (record.key === -1) {
        const defaultValues = { is_active_seller: true };
        form.setFieldsValue(defaultValues);
        return { ...record, ...defaultValues };
      }
      return record;
    },
    [],
  );

  const columns = useMemo<any[]>(
    () => [
      {
        title: <>{t("resellers.is_active")}</>,
        dataIndex: "is_active_seller",
        key: "is_active_seller",
        inputType: "checkbox",
        required: false,
        sortable: true,
      },
      {
        title: <>{t("resellers.is_also_delivery_station")}</>,
        dataIndex: "is_also_delivery_station",
        key: "is_also_delivery_station",
        inputType: "checkbox",
        required: false,
        sortable: true,
      },
      {
        title: <>{t("resellers.is_reseller")}</>,
        dataIndex: "is_reseller",
        key: "is_reseller",
        inputType: "checkbox",
        required: false,
        sortable: true,
      },
      {
        title: (
          <>
            {t("resellers.name_for_member_pages")}
            <ToolTipIcon title={t("tooltip.name_for_member_pages")} />
          </>
        ),
        dataIndex: "name_for_member_pages",
        key: "name_for_member_pages",
        inputType: "text",
        width: "10em",
        required: false,
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
    ],
    [t, contactColumns],
  );

  return (
    <div>
      <h1>{t("resellers.list_sellers")}</h1>

      <HideInactiveSwitch value={hideInactive} onChange={setHideInactive} />

      <EditableTable
        columns={columns}
        apiFunctions={apiFunctions}
        initialData={filteredData}
        loading={isLoading}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        customSave={customSave}
        customEdit={customEdit}
        deleteContext={"sellers"}
        permissions={permissions}
        pagination={true}
        showSearchBar={true}
      />
      <ExplainerText title={t("common.info")}>
        {t("explainers.list_sellers")}
      </ExplainerText>

      {uploadAllowed && (
        <DownloadCsvTemplateButton
          columns={columns}
          filename={t("commissioning.sellers_template.csv")}
          modelName="reseller"
          onUploadSuccess={invalidateData}
        />
      )}
    </div>
  );
}
