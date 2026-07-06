import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
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
  EditableTable,
  gatedByPermissionOnlyEdit,
  wrapApiFunctions,
} from "@shared/tables";
import type {
  ApiFunctions,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { ExplainerText } from "@shared/ui";
import { useInvalidateAfterTableMutation } from "@hooks/index";

export default function ListStorages() {
  const { isOffice } = useRoles();
  const permissions = useMemo(
    () => gatedByPermissionOnlyEdit(isOffice),
    [isOffice],
  );
  const { data: rawData, isLoading } = useCommissioningStoragesList();
  const data = useMemo(
    () => (rawData ?? []) as unknown as TableRecord[],
    [rawData],
  );
  const queryClient = useQueryClient();
  const { t } = useTranslation();

  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningStoragesListQueryKey(),
    });
  }, [queryClient]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<Storage & TableRecord>({
        create: (payload) => commissioningStoragesCreate(payload),
        update: (id, payload) =>
          commissioningStoragesPartialUpdate(id, payload),
        delete: (id) => commissioningStoragesDestroy(id),
      }),
    [],
  );

  const customEdit = useCallback(
    (
      record: TableRecord,
      form: { setFieldsValue: (values: Record<string, unknown>) => void },
    ) => {
      if (record.key === -1) {
        const defaultValues = { is_active: true };
        form.setFieldsValue(defaultValues);
        return { ...record, ...defaultValues };
      }
      return record;
    },
    [],
  );

  const columns = useMemo<any[]>(
    () => [
      // isActiveColumn,
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
    <div>
      <h1>{t("commissioning.list_storages")}</h1>

      <EditableTable
        columns={columns}
        apiFunctions={apiFunctions}
        focusIndex="name"
        initialData={data}
        loading={isLoading}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        customEdit={customEdit}
        className="w-max custom-jasmin-table"
        uniqueCheck={["name"]}
        uniqueCheckMessage={t("validation.unique.name")}
        permissions={permissions}
      />
      <ExplainerText title={t("common.info")}>
        {t("explainers.list_storages")}
      </ExplainerText>
    </div>
  );
}
