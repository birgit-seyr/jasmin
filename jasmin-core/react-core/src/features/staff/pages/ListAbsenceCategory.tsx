import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  getStaffAbsenceCategoriesListQueryKey,
  staffAbsenceCategoriesCreate,
  staffAbsenceCategoriesDestroy,
  staffAbsenceCategoriesPartialUpdate,
  useStaffAbsenceCategoriesList,
} from "@shared/api/generated/staff/staff";
import type { AbsenceCategory } from "@shared/api/generated/models";
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

type AbsenceCategoryRow = AbsenceCategory & TableRecord;

const absenceCategoriesResource: CrudResource<AbsenceCategoryRow> = {
  useList: useStaffAbsenceCategoriesList,
  create: staffAbsenceCategoriesCreate,
  update: staffAbsenceCategoriesPartialUpdate,
  delete: staffAbsenceCategoriesDestroy,
  getListQueryKey: getStaffAbsenceCategoriesListQueryKey,
};

export default function ListAbsenceCategory() {
  const { t } = useTranslation();
  const { canEdit } = useRoles();
  const isActiveColumn = useIsActiveColumn();
  const permissions = useMemo(
    () => permissionsWithDeletable(canEdit),
    [canEdit],
  );

  const columns = useMemo<EditableColumnConfig<AbsenceCategoryRow>[]>(
    () => [
      // The shared column hook returns a loosely-typed config (inputType widened
      // to string); cast the one hook column rather than loosen the whole array.
      isActiveColumn as EditableColumnConfig<AbsenceCategoryRow>,
      {
        title: <>{t("common.year")}</>,
        dataIndex: "year",
        key: "year",
        inputType: "positive_integer",
        required: true,
        width: "7em",
        align: "right",
      },
      {
        title: <>{t("staff.name")}</>,
        dataIndex: "name",
        key: "name",
        inputType: "text",
        required: true,
        width: "18em",
        align: "left",
      },
    ],
    [isActiveColumn, t],
  );

  return (
    <CrudListPage<AbsenceCategoryRow>
      titleKey="staff.absence_categories"
      descriptionKey="staff.absence_categories_description"
      explainerKey="explainers.list_absence_categories"
      resource={absenceCategoriesResource}
      permissions={permissions}
      columns={columns}
      uniqueCheck={["year", "name"]}
      uniqueCheckMessage={t("staff.absence_category_year_name_unique")}
      focusIndex="name"
      className="w-max custom-jasmin-table"
    />
  );
}
