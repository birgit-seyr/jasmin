import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  cultivationBedTypesCreate,
  cultivationBedTypesDestroy,
  cultivationBedTypesPartialUpdate,
  getCultivationBedTypesListQueryKey,
  useCultivationBedTypesList,
} from "@shared/api/generated/cultivation/cultivation";
import type { BedType } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { useNumberFormat } from "@hooks/useNumberFormat";
import {
  CrudListPage,
  type CrudResource,
  permissionsWithDeletable,
} from "@shared/tables";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";

type BedTypeRow = BedType & TableRecord;

const bedTypesResource: CrudResource<BedTypeRow> = {
  useList: useCultivationBedTypesList,
  create: cultivationBedTypesCreate,
  update: cultivationBedTypesPartialUpdate,
  delete: cultivationBedTypesDestroy,
  getListQueryKey: getCultivationBedTypesListQueryKey,
};

export default function ListBedTypes() {
  const { t } = useTranslation();
  const { isGardener } = useRoles();
  const { format } = useNumberFormat();
  const permissions = useMemo(
    () => permissionsWithDeletable(isGardener),
    [isGardener],
  );

  const columns = useMemo<EditableColumnConfig<BedTypeRow>[]>(
    () => [
      {
        title: <>{t("cultivation.bed_type_name")}</>,
        dataIndex: "name",
        key: "name",
        inputType: "text",
        required: true,
        width: "14em",
        align: "left",
      },
      {
        title: <>{t("cultivation.length_in_m")}</>,
        dataIndex: "length_in_m",
        key: "length_in_m",
        inputType: "positive_integer",
        required: true,
        width: "9em",
      },
      {
        title: <>{t("cultivation.width_in_m")}</>,
        dataIndex: "width_in_m",
        key: "width_in_m",
        inputType: "positive_decimal2",
        required: true,
        width: "9em",
        render: (value: unknown) =>
          value == null || value === "" ? "" : format(Number(value), 2),
      },
    ],
    [t, format],
  );

  return (
    <CrudListPage<BedTypeRow>
      titleKey="cultivation.list_bed_types"
      descriptionKey="cultivation.bed_types_description"
      explainerKey="explainers.list_bed_types"
      resource={bedTypesResource}
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
