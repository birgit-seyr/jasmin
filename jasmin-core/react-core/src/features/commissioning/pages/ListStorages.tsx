import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningStoragesCreate,
  commissioningStoragesDestroy,
  commissioningStoragesPartialUpdate,
  getCommissioningStoragesListQueryKey,
  useCommissioningStoragesList,
} from "@shared/api/generated/commissioning/commissioning";
import type { Storage } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import {
  CrudListPage,
  type CrudResource,
  gatedByPermissionOnlyEdit,
} from "@shared/tables";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";

type StorageRow = Storage & TableRecord;

const storagesResource: CrudResource<StorageRow> = {
  useList: useCommissioningStoragesList,
  create: commissioningStoragesCreate,
  update: commissioningStoragesPartialUpdate,
  delete: commissioningStoragesDestroy,
  getListQueryKey: getCommissioningStoragesListQueryKey,
};

export default function ListStorages() {
  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const permissions = useMemo(
    () => gatedByPermissionOnlyEdit(isOffice),
    [isOffice],
  );

  const columns = useMemo<EditableColumnConfig<StorageRow>[]>(
    () => [
      {
        title: <>{t("commissioning.name")}</>,
        dataIndex: "name",
        key: "name",
        inputType: "text",
        required: true,
        width: "12em",
        align: "left",
      },
      {
        title: <>{t("commissioning.is_short_term_harvest_storage")}</>,
        dataIndex: "is_short_term_harvest_storage",
        key: "is_short_term_harvest_storage",
        inputType: "checkbox",
        required: false,
        disabled: true,
      },
      {
        title: <>{t("commissioning.is_long_term_storage")}</>,
        dataIndex: "is_long_term_harvest_storage",
        key: "is_long_term_harvest_storage",
        inputType: "checkbox",
        required: false,
        disabled: true,
      },
    ],
    [t],
  );

  return (
    <CrudListPage<StorageRow>
      titleKey="commissioning.list_storages"
      explainerKey="explainers.list_storages"
      resource={storagesResource}
      permissions={permissions}
      withHideInactive={false}
      columns={columns}
      uniqueCheck={["name"]}
      uniqueCheckMessage={t("validation.unique.name")}
      focusIndex="name"
      className="w-max custom-jasmin-table"
    />
  );
}
