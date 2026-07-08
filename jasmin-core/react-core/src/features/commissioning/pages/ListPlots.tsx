import { useMemo } from "react";
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
  CrudListPage,
  type CrudResource,
  permissionsWithDeletable,
} from "@shared/tables";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { useIsActiveColumn } from "@features/commissioning/hooks";

type PlotRow = Plot & TableRecord;

const plotsResource: CrudResource<PlotRow> = {
  useList: useCommissioningPlotsList,
  create: commissioningPlotsCreate,
  update: commissioningPlotsPartialUpdate,
  delete: commissioningPlotsDestroy,
  getListQueryKey: getCommissioningPlotsListQueryKey,
};

export default function ListPlots() {
  const { t } = useTranslation();
  const { canEdit } = useRoles();
  const isActiveColumn = useIsActiveColumn();
  const permissions = useMemo(
    () => permissionsWithDeletable(canEdit),
    [canEdit],
  );

  const columns = useMemo<EditableColumnConfig<PlotRow>[]>(
    () => [
      // The shared column hook returns a loosely-typed config (inputType widened
      // to string); cast the one hook column rather than loosen the whole array.
      isActiveColumn as EditableColumnConfig<PlotRow>,
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
    <CrudListPage<PlotRow>
      titleKey="commissioning.list_plots"
      descriptionKey="commissioning.plots_description"
      explainerKey="explainers.list_plots"
      resource={plotsResource}
      permissions={permissions}
      columns={columns}
      uniqueCheck={["name"]}
      uniqueCheckMessage={t("validation.unique.name")}
      focusIndex="name"
      className="w-max custom-jasmin-table"
    />
  );
}
