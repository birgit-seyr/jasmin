import { Tooltip } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  cultivationCultivationBatchesCreate,
  cultivationCultivationBatchesDestroy,
  cultivationCultivationBatchesPartialUpdate,
  getCultivationCultivationBatchesListQueryKey,
  useCultivationBedTypesList,
  useCultivationCultivationBatchesList,
  useCultivationVegetablesList,
} from "@shared/api/generated/cultivation/cultivation";
import type { CultivationBatch } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { YearSelector } from "@shared/selectors";
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
import { useNumberFormat } from "@hooks/useNumberFormat";

type BatchRow = CultivationBatch & TableRecord;

const batchesResource: CrudResource<BatchRow> = {
  useList: useCultivationCultivationBatchesList,
  create: cultivationCultivationBatchesCreate,
  update: cultivationCultivationBatchesPartialUpdate,
  delete: cultivationCultivationBatchesDestroy,
  getListQueryKey: getCultivationCultivationBatchesListQueryKey,
};

interface CultivationBatchListProps {
  /** Which side of the farm this page manages. */
  isGreenhouse: boolean;
  titleKey: string;
  descriptionKey: string;
  explainerKey: string;
}

/**
 * The cultivation-batch table, shared by the outdoor and greenhouse pages —
 * they differ only in the ``is_greenhouse`` flag, which both filters the list
 * and is stamped onto new rows.
 *
 * A batch is the planner's unit of work: a crop, when it goes in, when the
 * ground is free again, and how much space it needs. Only rows marked *final*
 * are fed to the solver, and only outdoor ones are placed by it.
 */
export default function CultivationBatchList({
  isGreenhouse,
  titleKey,
  descriptionKey,
  explainerKey,
}: CultivationBatchListProps) {
  const { t } = useTranslation();
  const { isGardener } = useRoles();
  const { format } = useNumberFormat();
  const [year, setYear] = useState<number>(new Date().getFullYear());

  const permissions = useMemo(
    () => permissionsWithDeletable(isGardener),
    [isGardener],
  );

  const { data: vegetables } = useCultivationVegetablesList();
  const vegetableOptions = useMemo<SelectOption[]>(
    () =>
      (vegetables ?? []).map((v) => ({
        value: v.id as string,
        label: v.name,
      })),
    [vegetables],
  );
  const vegetableNameById = useMemo(() => {
    const map = new Map<string, string>();
    (vegetables ?? []).forEach((v) => v.id && map.set(v.id, v.name));
    return map;
  }, [vegetables]);

  // The bed type the row's "beds" figure is measured in. The planner keeps the
  // crop inside that type's block, so an empty cell here genuinely means
  // "anywhere" rather than a forgotten field.
  const { data: bedTypes } = useCultivationBedTypesList();
  const bedTypeOptions = useMemo<SelectOption[]>(
    () =>
      (bedTypes ?? []).map((b) => ({
        value: b.id as string,
        label: b.name || (b.id as string),
      })),
    [bedTypes],
  );
  const bedTypeNameById = useMemo(() => {
    const map = new Map<string, string>();
    (bedTypes ?? []).forEach((b) => {
      if (b.id) map.set(b.id, b.name || b.id);
    });
    return map;
  }, [bedTypes]);

  const listParams = useMemo(
    () => ({ year, is_greenhouse: isGreenhouse }),
    [year, isGreenhouse],
  );
  const newRowDefaults = useMemo(
    () => ({ year, is_greenhouse: isGreenhouse, is_final: false }),
    [year, isGreenhouse],
  );

  const columns = useMemo<EditableColumnConfig<BatchRow>[]>(
    () => [
      {
        title: <>{t("cultivation.batch_vegetable")}</>,
        dataIndex: "vegetable",
        key: "vegetable",
        inputType: "select",
        required: true,
        width: "12em",
        align: "left",
        fixed: true,
        options: vegetableOptions,
        render: (value: unknown) =>
          value ? (vegetableNameById.get(String(value)) ?? "") : "",
      },
      {
        title: <>{t("cultivation.planting_week")}</>,
        dataIndex: "planting_week",
        key: "planting_week",
        inputType: "kw",
        required: true,
        width: "7em",
      },
      {
        title: <>{t("cultivation.harvesting_start_week")}</>,
        dataIndex: "harvesting_start_week",
        key: "harvesting_start_week",
        inputType: "kw",
        required: true,
        width: "7em",
      },
      {
        title: <>{t("cultivation.harvesting_end_week")}</>,
        dataIndex: "harvesting_end_week",
        key: "harvesting_end_week",
        inputType: "kw",
        required: true,
        width: "7em",
      },
      {
        title: <>{t("cultivation.end_week")}</>,
        dataIndex: "end_week",
        key: "end_week",
        inputType: "kw",
        required: true,
        width: "7em",
      },
      {
        title: <>{t("cultivation.amount_of_beds")}</>,
        dataIndex: "amount_of_beds",
        key: "amount_of_beds",
        inputType: "positive_decimal2",
        required: true,
        width: "8em",
        render: (value: unknown) =>
          value == null || value === "" ? "" : format(Number(value), 2),
      },
      {
        // Sits beside the bed count on purpose: together they read "3 beds of
        // Standard 50 m", which is what the number actually means.
        title: (
          <Tooltip title={t("cultivation.batch_used_bed_type_hint")}>
            {t("cultivation.batch_used_bed_type")}
          </Tooltip>
        ),
        dataIndex: "used_bed_type",
        key: "used_bed_type",
        inputType: "select",
        required: false,
        width: "12em",
        align: "left",
        options: bedTypeOptions,
        render: (value: unknown) =>
          value ? (bedTypeNameById.get(String(value)) ?? "") : "",
      },
      {
        title: <>{t("cultivation.batch_planting_lines")}</>,
        dataIndex: "planting_lines",
        key: "planting_lines",
        inputType: "positive_integer",
        required: true,
        width: "7em",
      },
      {
        title: <>{t("cultivation.week_when_fleece_is_removed")}</>,
        dataIndex: "week_when_fleece_is_removed",
        key: "week_when_fleece_is_removed",
        inputType: "kw",
        required: false,
        width: "7em",
      },
      {
        title: <>{t("cultivation.is_final")}</>,
        dataIndex: "is_final",
        key: "is_final",
        inputType: "checkbox",
        required: false,
        width: "6em",
      },
      {
        title: <>{t("cultivation.note")}</>,
        dataIndex: "note",
        key: "note",
        inputType: "text",
        required: false,
        width: "12em",
        align: "left",
      },
    ],
    [
      t,
      vegetableOptions,
      vegetableNameById,
      bedTypeOptions,
      bedTypeNameById,
      format,
    ],
  );

  return (
    <CrudListPage<BatchRow>
      titleKey={titleKey}
      descriptionKey={descriptionKey}
      explainerKey={explainerKey}
      resource={batchesResource}
      permissions={permissions}
      withHideInactive={false}
      listParams={listParams}
      newRowDefaults={newRowDefaults}
      columns={columns}
      focusIndex="vegetable"
      className="w-max custom-jasmin-table"
      headerActions={
        <YearSelector selectedYear={year} setSelectedYear={setYear} />
      }
    />
  );
}
