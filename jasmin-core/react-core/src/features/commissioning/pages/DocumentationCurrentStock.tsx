import { useQueryClient } from "@tanstack/react-query";
import type { FormInstance } from "antd";
import dayjs from "dayjs";
import type { Key } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { dateForWeekDayNumber, isWeekInPast, toApiDate } from "@shared/utils";
import { useTranslation } from "react-i18next";
import {
  commissioningCurrentStockBulkFinalizeCreate,
  commissioningCurrentStockBulkSetAsExpectedCreate,
  commissioningCurrentStockBulkSetToZeroCreate,
  commissioningCurrentStockComparisonDestroy,
  commissioningCurrentStockComparisonPartialUpdate,
  getCommissioningCurrentStockComparisonListQueryKey,
  useCommissioningCurrentStockComparisonList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningCurrentStockComparisonListParams,
  CommissioningCurrentStockComparisonPartialUpdateBody,
  InventoryEntry,
  StockComparison,
} from "@shared/api/generated/models";
import { DaySelector, WeekSelector } from "@shared/selectors";
import { StorageSelector } from "@features/commissioning/selectors";
import { DocumentationCurrentStockMobileCard } from "@features/commissioning/components/mobileCards";
import { EditableTable, wrapApiFunctions } from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import {
  BulkActionButton,
  ExplainerText,
  MobileStack,
  PastWarningMessage,
  ToolTipIcon,
} from "@shared/ui";
import { AddShareArticleEntry } from "@features/commissioning/components";
import { useRoles } from "@shared/auth";

import {
  useInvalidateAfterTableMutation,
  currentWeek,
  useIsMobile,
  useNoteColumn,
  useNumberFormat,
  useTableRowSelection,
  useYearWeekState,
} from "@hooks/index";
import {
  useAmountUnitSizeColumns,
  useFinalColumn,
  useShareArticleColumn,
  useShareArticles,
} from "@features/commissioning/hooks";

const currentDay = dayjs().isoWeekday();

const shareArticleFilters = {
  is_active: true,
};

export default function DocumentationCurrentStock() {
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
  const [columnsLoaded, setColumnsLoaded] = useState(false);

  const { t } = useTranslation();
  const isMobile = useIsMobile();
  const { format } = useNumberFormat();

  const { finalColumn } = useFinalColumn();
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
    showAmount: false,
  });

  const { refetch: refetchShareArticles } =
    useShareArticles(shareArticleFilters);

  const {
    selectedRowKeys,
    onSelectedRowsChange: handleRowSelectionChange,
    rowSelection: rowSelectionConfig,
  } = useTableRowSelection((record: TableRecord) => record.key === -1);

  const listParams = useMemo<CommissioningCurrentStockComparisonListParams>(
    () => ({
      year: selectedYear,
      delivery_week: selectedWeek!,
      day_number: selectedDay!,
      ...(selectedStorage ? { storage: selectedStorage } : {}),
    }),
    [selectedYear, selectedWeek, selectedDay, selectedStorage],
  );

  useEffect(() => {
    if (
      shareArticleColumn &&
      amountUnitSizeColumns &&
      amountUnitSizeColumns.length > 0
    ) {
      setColumnsLoaded(true);
    }
  }, [shareArticleColumn, amountUnitSizeColumns]);

  // React Query — failures route through the global queryCache.onError
  // toast. Writes call `invalidateData()` to trigger a refetch.
  const { data: rawData, isFetching } =
    useCommissioningCurrentStockComparisonList(listParams, {
      query: { enabled: columnsLoaded },
    });
  const data = useMemo<TableRecord[]>(
    () =>
      ((rawData ?? []) as StockComparison[]).map((item) => ({
        ...item,
        key: item.id,
      })) as unknown as TableRecord[],
    [rawData],
  );
  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningCurrentStockComparisonListQueryKey(listParams),
    });
  }, [queryClient, listParams]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

  const currentDate = useMemo(() => {
    return dateForWeekDayNumber(
      selectedYear,
      selectedWeek ?? currentWeek,
      selectedDay ?? 0,
    );
  }, [selectedYear, selectedWeek, selectedDay]);

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => {
      // Coerce the five boolean inventory flags to ``false`` when
      // the row has them nullish. The backend model fields
      // (``MovementShareArticle.for_shares`` / ``for_resellers`` /
      // ``for_markets`` / ``washed`` / ``cleaned``) are
      // ``BooleanField(default=False)`` WITHOUT ``null=True`` — so
      // sending ``null`` makes Django's ``full_clean()`` reject
      // the save with "This field cannot be null." An unchecked
      // checkbox semantically IS ``false``, not "leave alone", so
      // we send it that way explicitly rather than relying on the
      // backend to skip nulls.
      const bool = (v: unknown) => (v == null ? false : Boolean(v));
      return {
        ...transformedData,
        for_shares: bool(transformedData.for_shares),
        for_resellers: bool(transformedData.for_resellers),
        for_markets: bool(transformedData.for_markets),
        washed: bool(transformedData.washed),
        cleaned: bool(transformedData.cleaned),
        date: toApiDate(currentDate)!,
        year: selectedYear,
        delivery_week: selectedWeek ?? currentWeek,
        day_number: selectedDay ?? 0,
        storage: selectedStorage ?? undefined,
      };
    },
    [currentDate, selectedYear, selectedWeek, selectedDay, selectedStorage],
  );

  const customEdit = useCallback((record: TableRecord, form: FormInstance) => {
    if (record.key === -1) {
      const defaultValues = {
        size: "M",
        for_shares: true,
        for_resellers: true,
        washed: false,
        cleaned: false,
      };
      form.setFieldsValue(defaultValues);
      return { ...record, ...defaultValues };
    }

    // If amount is empty, default both flags to true
    const amount = record.amount;
    if (amount === null || amount === undefined || amount === "") {
      const defaults = { for_shares: true, for_resellers: true };
      form.setFieldsValue(defaults);
      return { ...record, ...defaults };
    }

    return record;
  }, []);

  const buildCompositeId = useCallback(
    (row: Record<string, unknown>) => {
      const saId = row.share_article;
      const unit = row.unit ?? "None";
      const size = row.size ?? "None";
      const storageId = row.storage ?? selectedStorage ?? "None";
      return `${saId}_${unit}_${size}_${storageId}_${selectedYear}_${selectedWeek ?? currentWeek}_${selectedDay ?? 0}`;
    },
    [selectedYear, selectedWeek, selectedDay, selectedStorage],
  );

  const customUpdate = useCallback(
    async (key: Key, transformedRow: Record<string, unknown>) => {
      const compositeId =
        key === -1 ? buildCompositeId(transformedRow) : String(key);
      // ``composite_id`` is the PATH param — the phantom duplicate
      // query param was removed from the schema.
      const result = await commissioningCurrentStockComparisonPartialUpdate(
        String(compositeId),
        transformedRow as unknown as CommissioningCurrentStockComparisonPartialUpdateBody,
      );
      const entry = result as InventoryEntry;
      return { ...entry, key: entry?.id ?? compositeId };
    },
    [buildCompositeId],
  );

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions({
        delete: (id) => commissioningCurrentStockComparisonDestroy(id),
      }),
    [],
  );

  const columns = useMemo<EditableColumnConfig<TableRecord>[]>(
    () => [
      finalColumn,
      {
        ...shareArticleColumn,
        disabled: (record: TableRecord) => record.key != -1,
      },
      ...amountUnitSizeColumns,

      {
        title: (
          <>
            {t("commissioning.expected_stock")}
            <ToolTipIcon
              title={t("tooltip.negative_amounts_in_current_stock")}
            />
          </>
        ),
        dataIndex: "theoretical_current_stock",
        key: "theoretical_current_stock",
        required: false,
        width: "8em",
        align: "center",
        disabled: true,
        readOnly: true,
        render: (value: unknown) => {
          if (value === null || value === undefined || value === "") return "-";
          return format(parseFloat(String(value)), 0);
        },
      },
      {
        title: <>{t("commissioning.actual_stock")}</>,
        dataIndex: "amount",
        key: "amount",
        inputType: "positive_integer",
        required: false,
        width: "8em",
        align: "center",
        disabled: false,
        readOnly: false,
        render: (value: unknown) => {
          if (value === null || value === undefined || value === "") return "-";
          return format(parseFloat(String(value)), 0);
        },
      },
      {
        title: <>{t("commissioning.for_shares")}</>,
        dataIndex: "for_shares",
        key: "for_shares",
        inputType: "checkbox",
        required: false,
      },
      {
        title: <>{t("commissioning.for_resellers")}</>,
        dataIndex: "for_resellers",
        key: "for_resellers",
        inputType: "checkbox",
        required: false,
      },
      // {
      //   title: <>{t("commissioning.washed")}</>,
      //   dataIndex: "washed",
      //   key: "washed",
      //   inputType: "checkbox",
      //   required: false,
      // },
      // {
      //   title: <>{t("commissioning.cleaned")}</>,
      //   dataIndex: "cleaned",
      //   key: "cleaned",
      //   inputType: "checkbox",
      //   required: false,
      // },
      {
        ...noteColumn,
        inputType: "optional",
        width: "25em",
      },
    ],
    [
      finalColumn,
      shareArticleColumn,
      amountUnitSizeColumns,
      t,
      format,
      noteColumn,
    ],
  );

  // Staff can add + edit while the week isn't past; rows are never deleted here.
  const permissions = useMemo(
    () => ({
      canAdd: isStaff && !isPast,
      canEdit: isStaff && !isPast,
      canDelete: false,
    }),
    [isStaff, isPast],
  );

  return (
    <div>
      <h1>{t("commissioning.documentation_amounts")}</h1>

      <MobileStack>
        <WeekSelector
          selectedYear={selectedYear}
          setSelectedYear={setSelectedYear}
          selectedWeek={selectedWeek}
          setSelectedWeek={setSelectedWeek}
        />
        <DaySelector
          selectedDay={selectedDay}
          setSelectedDay={setSelectedDay}
          selectedWeek={selectedWeek ?? currentWeek}
          selectedYear={selectedYear}
          days={[0, 1, 2, 3, 4, 5, 6]}
        />

        <StorageSelector
          selectedStorage={selectedStorage}
          setSelectedStorage={setSelectedStorage}
        />
      </MobileStack>
      {!isPast && !isMobile && (
        <div className="bulk-actions-header">
          <strong>{t("commissioning.for_selected")}</strong>
        </div>
      )}
      {!isPast && !isMobile && (
        <div className="button-row-spaced">
          <BulkActionButton
            selectedIds={selectedRowKeys}
            apiFunction={(payload) =>
              commissioningCurrentStockBulkFinalizeCreate({
                ids: (payload.ids as string[]) ?? [],
              })
            }
            buttonText={t("commissioning.finalize")}
            buttonProps={{ type: "primary" }}
            disabled={selectedRowKeys.length === 0}
            onSuccess={invalidateData}
          />
          <ToolTipIcon
            title={t("tooltip.finalize")}
            className="tooltip-icon-bulk-action"
          />

          <BulkActionButton
            selectedIds={selectedRowKeys}
            apiFunction={(payload) =>
              commissioningCurrentStockBulkSetAsExpectedCreate({
                ids: (payload.ids as string[]) ?? [],
              })
            }
            buttonText={t("commissioning.set_as_expected_stock")}
            buttonProps={{ type: "primary" }}
            disabled={selectedRowKeys.length === 0}
            onSuccess={invalidateData}
          />

          <BulkActionButton
            selectedIds={selectedRowKeys}
            apiFunction={(payload) =>
              commissioningCurrentStockBulkSetToZeroCreate({
                ids: (payload.ids as string[]) ?? [],
              })
            }
            buttonText={t("commissioning.set_to_zero")}
            buttonProps={{ type: "primary" }}
            disabled={selectedRowKeys.length === 0}
            onSuccess={invalidateData}
          />
        </div>
      )}
      {isPast && (
        <PastWarningMessage>{t("table.past_week_readonly")}</PastWarningMessage>
      )}

      <div className="alert-banner alert-banner-danger">
        {t("commissioning.inventory_end_of_day_note")}
      </div>

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
        customUpdate={customUpdate}
        permissions={permissions}
        rowSelection={!isPast && !isMobile ? rowSelectionConfig : undefined}
        onSelectedRowsChange={handleRowSelectionChange}
        selectedRowKeys={selectedRowKeys}
        uniqueCheck={["share_article", "unit", "size"]}
        uniqueCheckMessage={t(
          "validation.unique.share_article_unit_size_must_be_unique",
        )}
        renderMobileCard={(
          record: TableRecord,
          onEdit: (r: TableRecord) => void,
        ) => (
          <DocumentationCurrentStockMobileCard
            key={String(record.key)}
            record={record}
            onEdit={onEdit}
          />
        )}
      />
      <AddShareArticleEntry
        disabled={isPast}
        onSuccess={() => refetchShareArticles()}
      />

      {!isMobile && (
        <ExplainerText title={t("common.info")}>
          {t("explainers.currentstock")}
        </ExplainerText>
      )}
    </div>
  );
}
