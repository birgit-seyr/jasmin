import { useCallback, useMemo } from "react";
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
  CrudListPage,
  type CrudResource,
  permissionsWithDeletable,
} from "@shared/tables";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import { DownloadCsvTemplateButton, ToolTipIcon } from "@shared/ui";
import { useContactColumns, useTenant } from "@hooks/index";
import { isFieldDisabled } from "@shared/utils";

type ResellerRow = Reseller & TableRecord;

// Sellers are Resellers scoped to ``is_seller`` — the list hook AND the query
// key take this so invalidation targets the same cached query.
const SELLER_LIST_PARAMS: CommissioningResellersListParams = { is_seller: true };
const NEW_SELLER_DEFAULTS = { is_active_seller: true };

const sellersResource: CrudResource<ResellerRow> = {
  useList: useCommissioningResellersList,
  create: commissioningResellersCreate,
  update: commissioningResellersPartialUpdate,
  // A Reseller can be seller AND reseller, so a seller-page delete is a scoped
  // unset-of-role (soft), not a hard delete — hence the fixed delete_context.
  delete: (id) =>
    commissioningResellersDestroy(id, { delete_context: "sellers" }),
  getListQueryKey: getCommissioningResellersListQueryKey,
};

export default function ListSellers() {
  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const { getSetting } = useTenant();
  const permissions = useMemo(
    () => permissionsWithDeletable(isOffice),
    [isOffice],
  );
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

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => ({
      ...transformedData,
      is_seller: true,
      comes_from_seller_page: true,
    }),
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
    <CrudListPage<ResellerRow>
      titleKey="resellers.list_sellers"
      explainerKey="explainers.list_sellers"
      resource={sellersResource}
      permissions={permissions}
      listParams={SELLER_LIST_PARAMS}
      activeField="is_active_seller"
      newRowDefaults={NEW_SELLER_DEFAULTS}
      columns={columns}
      customSave={customSave}
      deleteContext="sellers"
      pagination
      showSearchBar
    >
      {(list) =>
        uploadAllowed ? (
          <DownloadCsvTemplateButton
            columns={columns}
            filename={t("commissioning.sellers_template.csv")}
            modelName="reseller"
            onUploadSuccess={list.invalidate}
          />
        ) : null
      }
    </CrudListPage>
  );
}
