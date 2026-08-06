import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  cultivationVegetablesCreate,
  cultivationVegetablesDestroy,
  cultivationVegetablesPartialUpdate,
  getCultivationVegetablesListQueryKey,
  useCultivationCultivationBreakFamiliesList,
  useCultivationVegetablesList,
} from "@shared/api/generated/cultivation/cultivation";
import {
  VegetableUnitEnum,
  type Vegetable,
} from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { useNumberFormat } from "@hooks/useNumberFormat";
import { useUnitOptions } from "@hooks/useUnitOptions";
import {
  CrudListPage,
  type CrudResource,
  permissionsWithDeletable,
} from "@shared/tables";
import type {
  EditableColumnConfig,
  SelectOption,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import {
  useFertilizerOptions,
  usePlantingModeOptions,
} from "../hooks/useVegetableEnumOptions";

type VegetableRow = Vegetable & TableRecord;

const vegetablesResource: CrudResource<VegetableRow> = {
  useList: useCultivationVegetablesList,
  create: cultivationVegetablesCreate,
  update: cultivationVegetablesPartialUpdate,
  delete: cultivationVegetablesDestroy,
  getListQueryKey: getCultivationVegetablesListQueryKey,
};

// Empty-safe decimal cell: routes the backend's canonical "."-string through the
// locale-aware formatter (never prints the raw "12.500").
const decimalRender =
  (format: (n: number, dp: number) => string, dp: number) =>
  (value: unknown) =>
    value == null || value === "" ? "" : format(Number(value), dp);

export default function ListVegetables() {
  const { t } = useTranslation();
  const { isGardener } = useRoles();
  const { format } = useNumberFormat();
  const { unitOptions, getUnitLabel } = useUnitOptions();
  const { options: plantingModeOptions, getLabel: getPlantingModeLabel } =
    usePlantingModeOptions();
  const { options: fertilizerOptions, getLabel: getFertilizerLabel } =
    useFertilizerOptions();

  // Crop-rotation family FK: options + id→name map, both from the shared list
  // hook (plain array — the API is unpaginated).
  const { data: families } = useCultivationCultivationBreakFamiliesList();
  const familyOptions = useMemo<SelectOption[]>(
    () =>
      (families ?? []).map((f) => ({
        value: f.id as string,
        label: f.name,
      })),
    [families],
  );
  const familyNameById = useMemo(() => {
    const map = new Map<string, string>();
    (families ?? []).forEach((f) => {
      if (f.id) map.set(f.id, f.name);
    });
    return map;
  }, [families]);

  const permissions = useMemo(
    () => permissionsWithDeletable(isGardener),
    [isGardener],
  );

  const columns = useMemo<EditableColumnConfig<VegetableRow>[]>(
    () => [
      {
        title: <>{t("cultivation.vegetable_name")}</>,
        dataIndex: "name",
        key: "name",
        inputType: "text",
        required: true,
        width: "14em",
        align: "left",
        fixed: true,
      },
      {
        title: <>{t("cultivation.unit")}</>,
        dataIndex: "unit",
        key: "unit",
        inputType: "select",
        required: true,
        width: "8em",
        align: "center",
        options: unitOptions as unknown as SelectOption[],
        render: (value: unknown) => getUnitLabel(String(value ?? "")),
      },

      {
        title: <>{t("cultivation.fertilizer_requirement")}</>,
        dataIndex: "fertilizer_requirement",
        key: "fertilizer_requirement",
        inputType: "select",
        required: true,
        width: "10em",
        align: "center",

        options: fertilizerOptions as unknown as SelectOption[],
        render: (value: unknown) => getFertilizerLabel(String(value ?? "")),
      },
      {
        title: <>{t("cultivation.cultivation_break_family")}</>,
        dataIndex: "cultivation_break_family",
        key: "cultivation_break_family",
        inputType: "select",
        required: false,
        width: "13em",
        align: "left",
        options: familyOptions,
        render: (value: unknown) =>
          value ? (familyNameById.get(String(value)) ?? "") : "",
      },
      {
        title: <>{t("cultivation.default_planting_mode")}</>,
        dataIndex: "default_planting_mode",
        key: "default_planting_mode",
        inputType: "select",
        required: true,
        align: "center",
        width: "8em",
        options: plantingModeOptions as unknown as SelectOption[],
        render: (value: unknown) => getPlantingModeLabel(String(value ?? "")),
      },
      {
        title: <>{t("cultivation.default_planting_lines")}</>,
        dataIndex: "default_planting_lines",
        key: "default_planting_lines",
        inputType: "positive_integer",
        required: true,
        align: "center",

        width: "9em",
      },
      {
        title: <>{t("cultivation.default_distance_in_row")}</>,
        dataIndex: "default_distance_in_row",
        key: "default_distance_in_row",
        inputType: "positive_decimal2",
        required: true,
        align: "center",

        width: "9em",
        render: decimalRender(format, 2),
      },
      {
        title: <>{t("cultivation.default_pieces_per_plant")}</>,
        dataIndex: "default_pieces_per_plant",
        key: "default_pieces_per_plant",
        inputType: "positive_integer",
        required: false,
        align: "center",
        width: "9em",
      },
      {
        title: <>{t("cultivation.average_kg_per_piece")}</>,
        dataIndex: "average_kg_per_piece",
        key: "average_kg_per_piece",
        inputType: "positive_decimal3",
        required: true,
        width: "9em",
        align: "center",
        render: decimalRender(format, 3),
      },
      {
        title: <>{t("cultivation.default_yield_kg_per_m2")}</>,
        dataIndex: "default_yield_kg_per_m2",
        key: "default_yield_kg_per_m2",
        inputType: "positive_decimal3",
        required: false,
        width: "9em",
        // Yield per m² is only meaningful for kg-sold crops — editable only
        // when the row's unit is KG (mirrors commissioning's per-record
        // `disabled: (record) => …` columns).
        disabled: (record) => record.unit !== VegetableUnitEnum.KG,
        render: decimalRender(format, 3),
      },
    ],
    [
      t,
      format,
      unitOptions,
      getUnitLabel,
      fertilizerOptions,
      getFertilizerLabel,
      familyOptions,
      familyNameById,
      plantingModeOptions,
      getPlantingModeLabel,
    ],
  );

  return (
    <CrudListPage<VegetableRow>
      titleKey="cultivation.list_vegetables"
      descriptionKey="cultivation.vegetables_description"
      explainerKey="explainers.list_vegetables"
      resource={vegetablesResource}
      permissions={permissions}
      withHideInactive={false}
      columns={columns}
      uniqueCheck={["name"]}
      uniqueCheckMessage={t("validation.unique.name")}
      focusIndex="name"
      className="w-max custom-jasmin-table"
      pagination={true}
    />
  );
}
