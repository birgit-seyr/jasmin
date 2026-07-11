import { useQueryClient } from "@tanstack/react-query";
import type { FormInstance } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo, useState } from "react";
import { isWeekInPast } from "@shared/utils";
import { useTranslation } from "react-i18next";
import {
  commissioningWasteCreate,
  commissioningWasteDestroy,
  commissioningWastePartialUpdate,
  getCommissioningWasteListQueryKey,
  useCommissioningWasteList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningWasteListParams,
  Waste,
} from "@shared/api/generated/models";
import { DaySelector, WeekSelector } from "@shared/selectors";
import { StorageSelector } from "@features/commissioning/selectors";
import {
  EditableTable,
  gatedByPermission,
  wrapApiFunctions,
} from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { ExplainerText, MobileStack, PastWarningMessage } from "@shared/ui";
import { AddShareArticleEntry } from "@features/commissioning/components";
import { useRoles } from "@shared/auth";
import {
  currentWeek,
  useInvalidateAfterTableMutation,
  useNoteColumn,
  useYearWeekState,
} from "@hooks/index";
import {
  useAmountUnitSizeColumns,
  useShareArticleColumn,
  useShareArticles,
} from "@features/commissioning/hooks";

const currentDay = dayjs().isoWeekday();

const shareArticleFilters = {
  is_active: true,
};

export default function DocumentationWaste() {
  const { isStaff } = useRoles();
  const { selectedYear, setSelectedYear, selectedWeek, setSelectedWeek } =
    useYearWeekState();
  const [selectedDay, setSelectedDay] = useState<number | null>(currentDay - 1);
  const [selectedStorage, setSelectedStorage] = useState<string | null>(null);
  const isPast = useMemo(
    () => isWeekInPast(selectedYear, selectedWeek),
    [selectedYear, selectedWeek],
  );
  const queryClient = useQueryClient();
  const permissions = useMemo(
    () => gatedByPermission(isStaff && !isPast),
    [isStaff, isPast],
  );

  const { noteColumn } = useNoteColumn();
  const { shareArticleColumn } = useShareArticleColumn({
    filters: shareArticleFilters,
    showFruitsAndVegs: true,
    articleDefaults: "harvest",
  });

  const { amountUnitSizeColumns } = useAmountUnitSizeColumns({
    overrides: {
      unit: {
        disabled: (record: Record<string, unknown>) => {
          if (record.key != -1) return true;
        },
      },
      size: {
        disabled: (record: Record<string, unknown>) => {
          if (record.key != -1) return true;
        },
      },
    },
  });

  const { t } = useTranslation();

  const { refetch: refetchShareArticles } =
    useShareArticles(shareArticleFilters);

  const listParams = useMemo<CommissioningWasteListParams>(
    () => ({
      year: selectedYear,
      delivery_week: selectedWeek!,
      day_number: selectedDay!,
      is_past: isPast,
    }),
    [selectedYear, selectedWeek, selectedDay, isPast],
  );

  // React Query — failures route through the global queryCache.onError
  // toast. Writes call `invalidateData()` to trigger a refetch.
  const { data: rawData, isFetching } = useCommissioningWasteList(listParams, {
    query: { enabled: !!selectedStorage },
  });
  const data = useMemo(() => {
    const items = (rawData ?? []) as unknown as Array<Record<string, unknown>>;
    return items
      .filter((item) => item[`storage_${selectedStorage}`])
      .map((item) => ({ ...item, key: item.id ?? "" })) as unknown as TableRecord[];
  }, [rawData, selectedStorage]);
  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningWasteListQueryKey(listParams),
    });
  }, [queryClient, listParams]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => ({
      ...transformedData,
      storage: selectedStorage,
      year: selectedYear,
      delivery_week: selectedWeek ?? currentWeek,
      day_number: selectedDay,
    }),
    [selectedYear, selectedWeek, selectedDay, selectedStorage],
  );

  const customEdit = useCallback((record: TableRecord, form: FormInstance) => {
    if (record.key === -1) {
      const defaultValues = { size: "M" };
      form.setFieldsValue(defaultValues);
      return { ...record, ...defaultValues } as TableRecord;
    }
    return record;
  }, []);

  const columns = useMemo<EditableColumnConfig<TableRecord>[]>(
    () => [
      {
        ...shareArticleColumn,
        disabled: (record: TableRecord) => record.key != -1,
      },
      ...amountUnitSizeColumns,
      {
        ...noteColumn,
        width: "35em",
      },
    ],
    [shareArticleColumn, amountUnitSizeColumns, noteColumn],
  );

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<Waste & TableRecord>({
        create: (payload) => commissioningWasteCreate(payload),
        update: (id, payload) => commissioningWastePartialUpdate(id, payload),
        delete: (id) => commissioningWasteDestroy(id),
      }),
    [],
  );

  return (
    <div>
      <h1>{t("commissioning.documentation_waste")}</h1>

      <MobileStack>
        <WeekSelector
          selectedYear={selectedYear}
          setSelectedYear={setSelectedYear}
          selectedWeek={selectedWeek}
          setSelectedWeek={setSelectedWeek}
        />
        <DaySelector
          selectedYear={selectedYear}
          selectedWeek={selectedWeek ?? currentWeek}
          selectedDay={selectedDay}
          setSelectedDay={setSelectedDay}
          days={[0, 1, 2, 3, 4, 5, 6]}
        />
        <StorageSelector
          selectedStorage={selectedStorage}
          setSelectedStorage={setSelectedStorage}
        />
      </MobileStack>

      {isPast && (
        <PastWarningMessage>{t("table.past_week_readonly")}</PastWarningMessage>
      )}

      <EditableTable
        key={`${selectedYear}-${selectedWeek}-${selectedDay}-${selectedStorage}`}
        columns={columns}
        apiFunctions={apiFunctions}
        focusIndex="share_article_name"
        initialData={data}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        loading={isFetching}
        customSave={customSave}
        customEdit={customEdit}
        permissions={permissions}
      />
      <AddShareArticleEntry
        disabled={isPast}
        onSuccess={() => refetchShareArticles()}
      />
      <ExplainerText title={t("common.info")}>
        {t("explainers.waste")}
      </ExplainerText>
    </div>
  );
}
