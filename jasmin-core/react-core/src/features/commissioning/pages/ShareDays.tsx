import { useQueryClient } from "@tanstack/react-query";
import dayjs from "dayjs";
import { useCallback, useMemo, useState, type Key } from "react";
import { isWeekInPast } from "@shared/utils";
import { getWeekdayChoices } from "@shared/utils/weekdayChoices";
import { useTranslation } from "react-i18next";
import {
  commissioningSharesBulkUpdateUpdate,
  commissioningSharesCreate,
  commissioningSharesDestroy,
  getCommissioningSharesGetDaysListQueryKey,
  useCommissioningSharesGetDaysList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningSharesGetDaysListParams,
  Share,
} from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { WeekSelector } from "@shared/selectors";
import { EditableTable, wrapApiFunctions } from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { ExplainerText, PastWarningMessage } from "@shared/ui";
import { useInvalidateAfterTableMutation } from "@hooks/index";

export default function ShareDays() {
  const [selectedYear, setSelectedYear] = useState(dayjs().year());
  const [selectedWeek, setSelectedWeek] = useState(dayjs().isoWeek());
  const isPast = useMemo(
    () => isWeekInPast(selectedYear, selectedWeek),
    [selectedYear, selectedWeek],
  );

  // Memoize so the same object reference is passed to the query hook and
  // the invalidator across renders. Previously a fresh object every render
  // meant the query hook saw a new params identity each cycle.
  const listParams = useMemo<CommissioningSharesGetDaysListParams>(
    () => ({
      year: selectedYear,
      delivery_week: selectedWeek,
    }),
    [selectedYear, selectedWeek],
  );

  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const queryClient = useQueryClient();

  const { data: rawData, isFetching } =
    useCommissioningSharesGetDaysList(listParams);
  const data = useMemo(
    () => (rawData ?? []) as unknown as TableRecord[],
    [rawData],
  );

  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningSharesGetDaysListQueryKey(listParams),
    });
  }, [queryClient, listParams]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

  const weekdayChoices = useMemo(() => getWeekdayChoices(t), [t]);

  const customUpdate = useCallback(
    async (
      key: Key,
      formData: Record<string, unknown>,
    ): Promise<TableRecord> => {
      if (!key || !formData) return {} as TableRecord;

      try {
        // Convert key (id) back to delivery_day
        // Since id = delivery_day + 1, delivery_day = id - 1
        const deliveryDay = parseInt(String(key)) - 1;

        // Prepare the data - remove undefined values and convert to null
        const dataToSend = Object.keys(formData).reduce<
          Record<string, unknown>
        >((acc, fieldKey) => {
          if (
            formData[fieldKey] === "undefined" ||
            formData[fieldKey] === undefined
          ) {
            acc[fieldKey] = null;
          } else {
            acc[fieldKey] = formData[fieldKey];
          }
          return acc;
        }, {});

        const response = await commissioningSharesBulkUpdateUpdate(
          dataToSend as unknown as Share,
          {
            year: selectedYear,
            delivery_week: selectedWeek,
            day_number: deliveryDay,
          },
        );

        // The response should be an array from get_days
        // Find the specific day that was updated
        const responseData = response as unknown as
          | Record<string, unknown>[]
          | Record<string, unknown>;
        const updatedDayData = Array.isArray(responseData)
          ? responseData.find((day) => day.delivery_day === deliveryDay)
          : responseData;

        if (!updatedDayData) {
          console.error("Could not find updated day data in response");
          return {} as TableRecord;
        }

        // Make sure it has the correct structure with id field
        return {
          ...updatedDayData,
          id: updatedDayData.id || (updatedDayData.delivery_day as number) + 1,
        } as TableRecord;
      } catch (error) {
        console.error("Update failed:", error);
        throw error;
      }
    },
    [selectedYear, selectedWeek],
  );

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<Share & TableRecord>({
        create: (payload) => commissioningSharesCreate(payload),
        delete: (id) => commissioningSharesDestroy(id),
      }),
    [],
  );

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => {
      return {
        ...transformedData,
        year: selectedYear,
        delivery_week: selectedWeek,
      };
    },
    [selectedYear, selectedWeek],
  );

  const columns = useMemo<EditableColumnConfig<TableRecord>[]>(
    () => [
    {
      title: t("configuration.delivery_day_shares"),
      dataIndex: "delivery_day",
      key: "delivery_day",
      inputType: "select",
      required: true,
      align: "center",
      width: "7em",
      options: weekdayChoices,
      render: (value: unknown) => {
        if (typeof value !== "number") return "-";
        const day = weekdayChoices.find((d) => d.value === value);
        return day ? day.label : value;
      },
      disabled: true,
    },
    {
      title: t("configuration.changed_delivery_day_shares"),
      dataIndex: "changed_day_number",
      key: "changed_day_number",
      inputType: "select",
      required: false,
      align: "center",
      width: "9em",
      options: weekdayChoices,
      render: (value: unknown) => {
        if (typeof value !== "number") return "-";
        const day = weekdayChoices.find((d) => d.value === value);
        return <span className="changed-day">{day ? day.label : value}</span>;
      },
      disabled: false,
    },
    // {
    //   title: t("configuration.default_get_current_stock_day"),
    //   dataIndex: "get_current_stock_day",
    //   key: "get_current_stock_day",
    //   inputType: "select",
    //   required: false,
    //   align: "center" as const,
    //   width: "5em",
    //   options: weekdayChoices,
    //   render: (value: unknown, record: TableRecord) => {
    //     if (typeof value !== "number") return "-";
    //     const day = weekdayChoices.find((d) => d.value === value);
    //     const displayValue = day ? day.label : value;

    //     if (record.get_current_stock_day_changed) {
    //       return <span className="changed-day">{displayValue}</span>;
    //     }

    //     return displayValue;
    //   },
    // },
    {
      title: t("configuration.default_washing_day"),
      dataIndex: "washing_day",
      key: "washing_day",
      inputType: "select",
      required: false,
      width: "7em",
      align: "center",
      options: weekdayChoices,
      render: (value: unknown, record: TableRecord) => {
        if (typeof value !== "number") return "-";
        const day = weekdayChoices.find((d) => d.value === value);
        const displayValue = day ? day.label : value;

        if (record.washing_day_changed) {
          return <span className="changed-day">{displayValue}</span>;
        }

        return displayValue;
      },
    },
    {
      title: t("configuration.default_cleaning_day"),
      dataIndex: "cleaning_day",
      key: "cleaning_day",
      inputType: "select",
      required: false,
      align: "center",
      width: "7em",
      options: weekdayChoices,
      render: (value: unknown, record: TableRecord) => {
        if (typeof value !== "number") return "-";
        const day = weekdayChoices.find((d) => d.value === value);
        const displayValue = day ? day.label : value;

        if (record.cleaning_day_changed) {
          return <span className="changed-day">{displayValue}</span>;
        }

        return displayValue;
      },
    },
    {
      title: t("configuration.default_harvesting_day"),
      dataIndex: "harvesting_day",
      key: "harvesting_day",
      inputType: "select",
      required: false,
      width: "7em",
      align: "center",
      options: weekdayChoices,
      render: (value: unknown, record: TableRecord) => {
        if (typeof value !== "number") return "-";
        const day = weekdayChoices.find((d) => d.value === value);
        const displayValue = day ? day.label : value;

        if (record.harvesting_day_changed) {
          return <span className="changed-day">{displayValue}</span>;
        }

        return displayValue;
      },
    },
    {
      title: t("configuration.default_packing_day"),
      dataIndex: "packing_day",
      key: "packing_day",
      inputType: "select",
      required: false,
      width: "7em",
      align: "center",
      options: weekdayChoices,
      render: (value: unknown, record: TableRecord) => {
        if (typeof value !== "number") return "-";
        const day = weekdayChoices.find((d) => d.value === value);
        const displayValue = day ? day.label : value;

        if (record.packing_day_changed) {
          return <span className="changed-day">{displayValue}</span>;
        }

        return displayValue;
      },
    },
    ],
    [t, weekdayChoices],
  );

  return (
    <div>
      <h1>{t("configuration.time_management_title")}</h1>
      <WeekSelector
        selectedYear={selectedYear}
        setSelectedYear={setSelectedYear}
        selectedWeek={selectedWeek}
        setSelectedWeek={(v) => v !== null && setSelectedWeek(v)}
      />
      {isPast && (
        <PastWarningMessage>{t("table.past_week_readonly")}</PastWarningMessage>
      )}
      <EditableTable
        columns={columns}
        apiFunctions={apiFunctions}
        focusIndex="delivery_day"
        initialData={data}
        loading={isFetching}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        customSave={customSave}
        customUpdate={customUpdate}
        permissions={{
          canAdd: false,
          canEdit: !isPast && isOffice,
          canDelete: false,
        }}
        className="w-max custom-forecast-table"
      />
      <ExplainerText title={t("common.info")}>
        {t("explainers.share_days")}
      </ExplainerText>
    </div>
  );
}
