import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  cultivationVegetableAggregationsCreate,
  cultivationVegetableAggregationsDestroy,
  cultivationVegetableAggregationsPartialUpdate,
  getCultivationVegetableAggregationsListQueryKey,
  useCultivationVegetableAggregationsList,
} from "@shared/api/generated/cultivation/cultivation";
import type { VegetableAggregation } from "@shared/api/generated/models";
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

type VegetableAggregationRow = VegetableAggregation & TableRecord;

const aggregationsResource: CrudResource<VegetableAggregationRow> = {
  useList: useCultivationVegetableAggregationsList,
  create: cultivationVegetableAggregationsCreate,
  update: cultivationVegetableAggregationsPartialUpdate,
  delete: cultivationVegetableAggregationsDestroy,
  getListQueryKey: getCultivationVegetableAggregationsListQueryKey,
};

export default function ListVegetableAggregations() {
  const { t } = useTranslation();
  const { isGardener } = useRoles();
  const permissions = useMemo(
    () => permissionsWithDeletable(isGardener),
    [isGardener],
  );

  const columns = useMemo<EditableColumnConfig<VegetableAggregationRow>[]>(
    () => [
      {
        title: <>{t("cultivation.aggregation_name")}</>,
        dataIndex: "name",
        key: "name",
        inputType: "text",
        required: true,
        width: "20em",
        align: "left",
      },
    ],
    [t],
  );

  return (
    <CrudListPage<VegetableAggregationRow>
      titleKey="cultivation.list_vegetable_aggregations"
      descriptionKey="cultivation.vegetable_aggregations_description"
      explainerKey="explainers.list_vegetable_aggregations"
      resource={aggregationsResource}
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
