import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  getStaffWeeklyPlanCategoriesListQueryKey,
  staffWeeklyPlanCategoriesCreate,
  staffWeeklyPlanCategoriesDestroy,
  staffWeeklyPlanCategoriesPartialUpdate,
  useStaffWeeklyPlanCategoriesList,
} from "@shared/api/generated/staff/staff";
import type { WeeklyPlanCategory } from "@shared/api/generated/models";
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

type WeeklyPlanCategoryRow = WeeklyPlanCategory & TableRecord;

const weeklyPlanCategoriesResource: CrudResource<WeeklyPlanCategoryRow> = {
  useList: useStaffWeeklyPlanCategoriesList,
  create: staffWeeklyPlanCategoriesCreate,
  update: staffWeeklyPlanCategoriesPartialUpdate,
  delete: staffWeeklyPlanCategoriesDestroy,
  getListQueryKey: getStaffWeeklyPlanCategoriesListQueryKey,
};

export default function ListWeeklyPlanCategory() {
  const { t } = useTranslation();
  const { canEdit } = useRoles();
  const isActiveColumn = useIsActiveColumn();
  const permissions = useMemo(
    () => permissionsWithDeletable(canEdit),
    [canEdit],
  );

  const columns = useMemo<EditableColumnConfig<WeeklyPlanCategoryRow>[]>(
    () => [
      // The shared column hook returns a loosely-typed config (inputType widened
      // to string); cast the one hook column rather than loosen the whole array.
      isActiveColumn as EditableColumnConfig<WeeklyPlanCategoryRow>,
      {
        title: <>{t("staff.name")}</>,
        dataIndex: "name",
        key: "name",
        inputType: "text",
        required: true,
        width: "18em",
        align: "left",
      },
      {
        title: <>{t("staff.max_lines")}</>,
        dataIndex: "max_lines",
        key: "max_lines",
        inputType: "positive_integer",
        required: true,
        width: "8em",
        align: "right",
      },
    ],
    [isActiveColumn, t],
  );

  return (
    <CrudListPage<WeeklyPlanCategoryRow>
      titleKey="staff.weekly_plan_categories"
      descriptionKey="staff.weekly_plan_categories_description"
      explainerKey="explainers.list_weekly_plan_categories"
      resource={weeklyPlanCategoriesResource}
      permissions={permissions}
      columns={columns}
      uniqueCheck={["name"]}
      uniqueCheckMessage={t("validation.unique.name")}
      focusIndex="name"
      className="w-max custom-jasmin-table"
    />
  );
}
