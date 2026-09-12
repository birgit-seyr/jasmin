import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  getStaffEmployeesListQueryKey,
  staffEmployeesCreate,
  staffEmployeesDestroy,
  staffEmployeesPartialUpdate,
  useStaffEmployeesList,
} from "@shared/api/generated/staff/staff";
import type { Employee } from "@shared/api/generated/models";
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

type EmployeeRow = Employee & TableRecord;

const employeesResource: CrudResource<EmployeeRow> = {
  useList: useStaffEmployeesList,
  create: staffEmployeesCreate,
  update: staffEmployeesPartialUpdate,
  delete: staffEmployeesDestroy,
  getListQueryKey: getStaffEmployeesListQueryKey,
};

export default function ListEmployees() {
  const { t } = useTranslation();
  const { canEdit } = useRoles();
  const isActiveColumn = useIsActiveColumn();
  const permissions = useMemo(
    () => permissionsWithDeletable(canEdit),
    [canEdit],
  );

  const columns = useMemo<EditableColumnConfig<EmployeeRow>[]>(
    () => [
      // The shared column hook returns a loosely-typed config (inputType widened
      // to string); cast the one hook column rather than loosen the whole array.
      isActiveColumn as EditableColumnConfig<EmployeeRow>,
      {
        title: <>{t("staff.short_name_for_weekly_plan")}</>,
        dataIndex: "short_name_for_weekly_plan",
        key: "short_name_for_weekly_plan",
        inputType: "text",
        required: true,
        width: "14em",
        align: "left",
      },
    ],
    [isActiveColumn, t],
  );

  return (
    <CrudListPage<EmployeeRow>
      titleKey="staff.employees"
      explainerKey="explainers.list_employees"
      resource={employeesResource}
      permissions={permissions}
      columns={columns}
      uniqueCheck={["short_name_for_weekly_plan"]}
      uniqueCheckMessage={t("validation.unique.name")}
      focusIndex="short_name_for_weekly_plan"
      className="w-max custom-jasmin-table"
    />
  );
}
