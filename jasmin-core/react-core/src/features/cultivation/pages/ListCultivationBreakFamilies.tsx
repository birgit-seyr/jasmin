import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  cultivationCultivationBreakFamiliesCreate,
  cultivationCultivationBreakFamiliesDestroy,
  cultivationCultivationBreakFamiliesPartialUpdate,
  getCultivationCultivationBreakFamiliesListQueryKey,
  useCultivationCultivationBreakFamiliesList,
} from "@shared/api/generated/cultivation/cultivation";
import type { CultivationBreakFamily } from "@shared/api/generated/models";
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

type CultivationBreakFamilyRow = CultivationBreakFamily & TableRecord;

const familiesResource: CrudResource<CultivationBreakFamilyRow> = {
  useList: useCultivationCultivationBreakFamiliesList,
  create: cultivationCultivationBreakFamiliesCreate,
  update: cultivationCultivationBreakFamiliesPartialUpdate,
  delete: cultivationCultivationBreakFamiliesDestroy,
  getListQueryKey: getCultivationCultivationBreakFamiliesListQueryKey,
};

export default function ListCultivationBreakFamilies() {
  const { t } = useTranslation();
  const { isGardener } = useRoles();
  const permissions = useMemo(
    () => permissionsWithDeletable(isGardener),
    [isGardener],
  );

  const columns = useMemo<EditableColumnConfig<CultivationBreakFamilyRow>[]>(
    () => [
      {
        title: <>{t("cultivation.break_family_name")}</>,
        dataIndex: "name",
        key: "name",
        inputType: "text",
        required: true,
        width: "18em",
        align: "left",
      },
      {
        title: <>{t("cultivation.cultivation_break_in_years")}</>,
        dataIndex: "cultivation_break_in_years",
        key: "cultivation_break_in_years",
        inputType: "positive_integer",
        required: true,
        width: "12em",
      },
    ],
    [t],
  );

  return (
    <CrudListPage<CultivationBreakFamilyRow>
      titleKey="cultivation.list_break_families"
      descriptionKey="cultivation.break_families_description"
      explainerKey="explainers.list_break_families"
      resource={familiesResource}
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
