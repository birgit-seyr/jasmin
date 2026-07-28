import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  cultivationPlotsCreate,
  cultivationPlotsDestroy,
  cultivationPlotsPartialUpdate,
  getCultivationPlotsListQueryKey,
  useCultivationPlotsList,
} from "@shared/api/generated/cultivation/cultivation";
import type { CultivationPlot } from "@shared/api/generated/models";
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

type PlotRow = CultivationPlot & TableRecord;

const plotsResource: CrudResource<PlotRow> = {
  useList: useCultivationPlotsList,
  create: cultivationPlotsCreate,
  update: cultivationPlotsPartialUpdate,
  delete: cultivationPlotsDestroy,
  getListQueryKey: getCultivationPlotsListQueryKey,
};

export default function ListPlots() {
  const { t } = useTranslation();
  const { isGardener } = useRoles();
  const permissions = useMemo(
    () => permissionsWithDeletable(isGardener),
    [isGardener],
  );

  const columns = useMemo<EditableColumnConfig<PlotRow>[]>(
    () => [
      {
        title: <>{t("cultivation.plot_name")}</>,
        dataIndex: "name",
        key: "name",
        inputType: "text",
        required: true,
        width: "16em",
        align: "left",
      },
      {
        title: <>{t("cultivation.is_greenhouse")}</>,
        dataIndex: "is_greenhouse",
        key: "is_greenhouse",
        inputType: "checkbox",
        required: false,
      },
    ],
    [t],
  );

  return (
    <CrudListPage<PlotRow>
      titleKey="cultivation.list_plots"
      descriptionKey="cultivation.plots_description"
      explainerKey="explainers.list_plots"
      resource={plotsResource}
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
