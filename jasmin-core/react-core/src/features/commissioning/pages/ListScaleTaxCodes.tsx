import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningScaleTaxCodesCreate,
  commissioningScaleTaxCodesDestroy,
  commissioningScaleTaxCodesPartialUpdate,
  getCommissioningScaleTaxCodesListQueryKey,
  useCommissioningScaleTaxCodesList,
} from "@shared/api/generated/commissioning/commissioning";
import type { ScaleTaxCode } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import {
  CrudListPage,
  type CrudResource,
  permissionsWithDeletable,
} from "@shared/tables";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";

type ScaleTaxCodeRow = ScaleTaxCode & TableRecord;

const scaleTaxCodesResource: CrudResource<ScaleTaxCodeRow> = {
  useList: useCommissioningScaleTaxCodesList,
  create: commissioningScaleTaxCodesCreate,
  update: commissioningScaleTaxCodesPartialUpdate,
  delete: commissioningScaleTaxCodesDestroy,
  getListQueryKey: getCommissioningScaleTaxCodesListQueryKey,
};

// A code has no active flag, so a new row starts empty. Module-level, since
// the list hook needs a stable object to keep its edit callback stable.
const NEW_ROW_DEFAULTS: Record<string, unknown> = {};

export default function ListScaleTaxCodes() {
  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const permissions = useMemo(
    () => permissionsWithDeletable(isOffice),
    [isOffice],
  );

  const columns = useMemo<EditableColumnConfig<ScaleTaxCodeRow>[]>(
    () => [
      {
        title: <>{t("commissioning.tax_rate")}</>,
        dataIndex: "tax_rate",
        key: "tax_rate",
        inputType: "positive_decimal2",
        required: true,
        suffix: "%",
        width: "8em",
        align: "right",
        render: (value: unknown) => (value == null ? "" : `${value} %`),
      },
      {
        title: <>{t("commissioning.scale_tax_code")}</>,
        dataIndex: "code",
        key: "code",
        inputType: "positive_integer",
        required: true,
        width: "8em",
        align: "right",
      },
    ],
    [t],
  );

  return (
    <CrudListPage<ScaleTaxCodeRow>
      titleKey="commissioning.list_scale_tax_codes"
      explainerKey="explainers.list_scale_tax_codes"
      resource={scaleTaxCodesResource}
      permissions={permissions}
      withHideInactive={false}
      newRowDefaults={NEW_ROW_DEFAULTS}
      columns={columns}
      focusIndex="tax_rate"
      uniqueCheck={["tax_rate"]}
      uniqueCheckMessage={t("validation.unique.tax_rate")}
      className="w-max custom-jasmin-table"
    />
  );
}
