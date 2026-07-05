import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningPlotsCreate,
  commissioningPlotsDestroy,
  commissioningPlotsPartialUpdate,
  getCommissioningPlotsListQueryKey,
  useCommissioningPlotsList,
} from "@shared/api/generated/commissioning/commissioning";
import type { Plot } from "@shared/api/generated/models";
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
import { ExplainerText, HideInactiveSwitch } from "@shared/ui";
import { useInvalidateAfterTableMutation } from "@hooks/index";
import { useIsActiveColumn } from "@features/commissioning/hooks";
export default function ListPlots() {
  const [hideInactive, setHideInactive] = useState(true);
  const queryClient = useQueryClient();
  const { t } = useTranslation();
  const { canEdit } = useRoles();
  const permissions = useMemo(
    () => permissionsWithDeletable(canEdit),
    [canEdit],
  );
  const isActiveColumn = useIsActiveColumn();

  // Page owns the data via ``useCommissioningPlotsList`` (passed as
  // ``initialData``); no ``list`` in ``apiFunctions`` so the table never
  // double-fetches. Mutations refresh through the invalidation below.
  const { data: rawData, isLoading } = useCommissioningPlotsList();
  const data = useMemo(
    () => (rawData ?? []) as unknown as TableRecord[],
    [rawData],
  );
  const filteredData = useMemo(
    () => (hideInactive ? data.filter((r) => r.is_active) : data),
    [data, hideInactive],
  );
  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningPlotsListQueryKey(),
    });
  }, [queryClient]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<Plot & TableRecord>({
        create: (payload) => commissioningPlotsCreate(payload),
        update: (id, payload) => commissioningPlotsPartialUpdate(id, payload),
        delete: (id) => commissioningPlotsDestroy(id),
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
      isActiveColumn,
      {
        title: <>{t("resellers.name")}</>,
        dataIndex: "name",
        key: "name",
        inputType: "text",
        required: false,
        width: "16em",
        align: "left",
      },
    ],
    [isActiveColumn, t],
  );

  return (
    <div>
      <h1>{t("commissioning.list_plots")}</h1>
      <h5>{t("commissioning.plots_description")}</h5>

      <HideInactiveSwitch value={hideInactive} onChange={setHideInactive} />

      <EditableTable
        columns={columns}
        apiFunctions={apiFunctions}
        focusIndex="name"
        initialData={filteredData}
        loading={isLoading}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        customEdit={customEdit}
        className="w-max custom-forecast-table"
        uniqueCheck={["name"]}
        uniqueCheckMessage={t("validation.unique.name")}
        permissions={permissions}
      />
      <ExplainerText title={t("common.info")}>
        {t("explainers.list_plots")}
      </ExplainerText>
    </div>
  );
}
