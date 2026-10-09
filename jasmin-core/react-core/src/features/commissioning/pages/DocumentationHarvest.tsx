import type { FormInstance } from "antd";
import { Button } from "antd";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningBulkFinalizeCreate,
  commissioningHarvestBulkSetAsExpectedCreate,
  commissioningHarvestCreate,
  commissioningHarvestDestroy,
  commissioningHarvestPartialUpdate,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  Harvest,
} from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { DocumentationHarvestMobileCard } from "@features/commissioning/components/mobileCards";
import { ExportCsvHarvest } from "@features/commissioning/modals";
import { DaySelector, WeekSelector } from "@shared/selectors";
import { StorageSelector } from "@features/commissioning/selectors";
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
import { formatAmountForUnit } from "@shared/utils";

import {
  useIsMobile,
  useNoteColumn,
  useNumberFormat,
  useTableRowSelection,
} from "@hooks/index";
import {
  useAmountUnitSizeColumns,
  useFinalColumn,
  useShareArticleColumn,
  useShareArticles,
  useStorageDocumentationPage,
} from "@features/commissioning/hooks";
import type { DocumentationSummaryRecord } from "@features/commissioning/hooks/useDocumentationSummaryPage";

const shareArticleFilters = {
  is_active: true,
  is_purchased: false,
};

export default function DocumentationHarvest() {
  const { isStaff } = useRoles();
  const [csvExportVisible, setCsvExportVisible] = useState(false);

  const { t } = useTranslation();
  const isMobile = useIsMobile();

  const { finalColumn } = useFinalColumn();
  const { noteColumn } = useNoteColumn();
  const { format } = useNumberFormat();

  const { shareArticleColumn } = useShareArticleColumn({
    filters: shareArticleFilters,
    showFruitsAndVegs: true,
    autofillContext: "harvest",
  });

  const { amountUnitSizeColumns } = useAmountUnitSizeColumns({
    showAmount: false,
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

  const { refetch: refetchShareArticles } =
    useShareArticles(shareArticleFilters);

  const {
    selectedRowKeys,
    onSelectedRowsChange: handleRowSelectionChange,
    rowSelection: rowSelectionConfig,
  } = useTableRowSelection((record: TableRecord) => record.key === -1);

  // A storage-matched harvest row is worth showing only if it carries a
  // theoretical, additional-theoretical, or actual harvest amount.
  const rowHasData = useCallback((item: DocumentationSummaryRecord) => {
    const theoreticalAmount = item.theoretical_harvest_amount;
    const additionalTheoreticalAmount =
      item.additional_theoretical_harvest_amount;
    // ``harvest_amount`` is a decimal string on the wire, so the zero check
    // needs a numeric coercion.
    const amount = item.harvest_amount;
    const isTheoreticalEmpty =
      theoreticalAmount == null || theoreticalAmount === 0;
    const isAdditionalTheoreticalEmpty =
      additionalTheoreticalAmount == null || additionalTheoreticalAmount === 0;
    const isAmountEmpty = amount == null || Number(amount) === 0;
    return !(
      isTheoreticalEmpty &&
      isAdditionalTheoreticalEmpty &&
      isAmountEmpty
    );
  }, []);

  // Shared year/week/day/is_past + summary query + storage selector/filter +
  // storage-stamped customSave + remount key. Harvest-specific bits (columns,
  // mutation endpoints, bulk actions) stay below. The query is gated until a
  // storage is picked.
  const {
    selectedYear,
    setSelectedYear,
    selectedWeek,
    currentWeek,
    setSelectedWeek,
    selectedDay,
    setSelectedDay,
    isPast,
    isFetching,
    invalidateData,
    onSaveSuccess,
    onDeleteSuccess,
    selectedStorage,
    setSelectedStorage,
    storages,
    data,
    tableKey,
    customSave,
  } = useStorageDocumentationPage({
    model: "harvest",
    rowHasData,
  });

  const isLongTermStorage = useMemo(() => {
    const storage = storages.find((s) => s.id === selectedStorage);
    return storage?.is_long_term_harvest_storage ?? false;
  }, [storages, selectedStorage]);

  // Theoretical harvests are short-term-locked, so "set as expected" only makes
  // sense for the short-term harvest storage; it's disabled for any other.
  const isShortTermStorage = useMemo(() => {
    const storage = storages.find((s) => s.id === selectedStorage);
    return storage?.is_short_term_harvest_storage ?? false;
  }, [storages, selectedStorage]);

  const customEdit = useCallback((record: TableRecord, form: FormInstance) => {
    if (record.key === -1) {
      const defaultValues: Record<string, unknown> = {
        size: "M",
      };

      form.setFieldsValue(defaultValues);
      return { ...record, ...defaultValues } as TableRecord;
    }

    const formValues: Record<string, unknown> = {};
    const recordUpdates: Record<string, unknown> = {};

    if (record.harvest_amount !== null && record.harvest_amount !== undefined) {
      formValues.amount = record.harvest_amount;
      recordUpdates.amount = record.harvest_amount;
    }

    if (Object.keys(formValues).length > 0) {
      form.setFieldsValue(formValues);
    }

    return { ...record, ...recordUpdates } as TableRecord;
  }, []);

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<Harvest & TableRecord>({
        create: (payload) => commissioningHarvestCreate(payload),
        update: (id, payload) => commissioningHarvestPartialUpdate(id, payload),
        delete: (id) => commissioningHarvestDestroy(id),
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
      ...(!isLongTermStorage
        ? ([
            {
              title: <>{t("commissioning.expected_harvest")}</>,
              dataIndex: "theoretical_harvest",
              key: "theoretical_harvest",
              inputType: "text",
              required: false,
              width: "8em",
              align: "center",
              disabled: true,
              readOnly: true,
              render: (_: unknown, record: Record<string, unknown>) => {
                const theoretical_amount =
                  (record.theoretical_harvest_amount as number) || 0;
                const additional_amount =
                  (record.additional_theoretical_harvest_amount as number) || 0;
                const totalAmount = theoretical_amount + additional_amount;
                return totalAmount > 0
                  ? formatAmountForUnit(
                      totalAmount,
                      record.unit as string,
                      format,
                    )
                  : "";
              },
            },
          ] as EditableColumnConfig<TableRecord>[])
        : []),
      {
        title: <>{t("commissioning.actual_harvest")}</>,
        dataIndex: "amount",
        key: "amount",
        inputType: "positive_decimal2",
        required: false,
        width: "8em",
        align: "center",
        disabled: false,
        readOnly: false,
        render: (_: unknown, record: Record<string, unknown>) =>
          record.harvest_amount == null || record.harvest_amount === ""
            ? ""
            : formatAmountForUnit(
                Number(record.harvest_amount),
                record.unit as string,
                format,
              ),
      },
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
      isLongTermStorage,
      t,
      noteColumn,
      format,
    ],
  );

  // Staff can add + edit while the week isn't past; adding also needs a
  // storage to stamp on the row. Delete is additionally hidden on mobile, and
  // a row can only be deleted while it carries no recorded (or additional)
  // theoretical harvest amount.
  const permissions = useMemo(
    () => ({
      canAdd: isStaff && !isPast && selectedStorage !== null,
      canEdit: isStaff && !isPast,
      canDelete: isStaff && !isPast && !isMobile,
      canDeleteRecord: (record: TableRecord) => {
        if (record.key === -1 || !record.id) {
          return true;
        }
        if (
          record.theoretical_harvest_amount != null &&
          record.theoretical_harvest_amount != 0
        ) {
          return false;
        }
        if (
          record.additional_theoretical_harvest_amount != null &&
          record.additional_theoretical_harvest_amount != 0
        ) {
          return false;
        }
        return true;
      },
    }),
    [isStaff, isPast, isMobile, selectedStorage],
  );

  return (
    <div>
      <h1>{t("commissioning.documentation_harvest")}</h1>
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
      {!isPast && !isMobile && !isLongTermStorage && (
        <div className="bulk-actions-header">
          <strong>{t("commissioning.for_selected")}</strong>
        </div>
      )}
      {!isPast && !isMobile && !isLongTermStorage && (
        <div className="button-row-spaced">
          <BulkActionButton
            selectedIds={selectedRowKeys}
            apiFunction={(payload) =>
              commissioningBulkFinalizeCreate({
                model: "harvest",
                app_label: "commissioning",
                ids: payload.ids,
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
          {selectedStorage && (
            <BulkActionButton
              selectedIds={selectedRowKeys}
              apiFunction={(payload) =>
                commissioningHarvestBulkSetAsExpectedCreate({
                  // A row without an article can't be set as expected — the
                  // button is enabled only for rows with a theoretical amount.
                  selectedData: payload.ids.flatMap((id) => {
                    const row = data.find((item) => item.id === id);
                    if (!row?.share_article) return [];
                    return [
                      {
                        id: row.share_article,
                        theoretical_harvest_amount: String(
                          row.theoretical_harvest_amount,
                        ),
                        theoretical_harvest_unit: row.unit,
                        theoretical_harvest_size: row.size,
                        year: selectedYear,
                        delivery_week: selectedWeek ?? currentWeek,
                        day_number: selectedDay ?? 0,
                        storage: selectedStorage,
                      },
                    ];
                  }),
                })
              }
              buttonText={
                t("commissioning.set_as_expected_harvest_for", {
                  storage:
                    storages.find((s) => s.id === selectedStorage)?.name ?? "",
                }) || t("commissioning.set_as_expected_harvest")
              }
              buttonProps={{ type: "primary" }}
              disabled={
                !isShortTermStorage ||
                selectedRowKeys.length === 0 ||
                selectedRowKeys.some((key) => {
                  const row = data.find((item) => item.id === key);
                  return (
                    row?.theoretical_harvest_amount == null ||
                    row.theoretical_harvest_amount === 0 ||
                    Number(row.harvest_amount) > 0
                  );
                })
              }
              onSuccess={invalidateData}
            />
          )}
        </div>
      )}
      {isPast && (
        <PastWarningMessage>{t("table.past_week_readonly")}</PastWarningMessage>
      )}
      <EditableTable
        key={tableKey}
        columns={columns}
        apiFunctions={apiFunctions}
        focusIndex="share_article_name"
        initialData={data}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        loading={isFetching}
        customSave={customSave}
        customEdit={customEdit}
        keyboardAddShortcut={true}
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
          onEdit: ((r: TableRecord) => void) | undefined,
        ) => (
          <DocumentationHarvestMobileCard
            key={String(record.key)}
            record={record}
            onEdit={onEdit}
            isLongTermStorage={isLongTermStorage}
          />
        )}
      />
      <ExportCsvHarvest
        open={csvExportVisible}
        onClose={() => setCsvExportVisible(false)}
      />
      <AddShareArticleEntry
        disabled={isPast}
        onSuccess={() => refetchShareArticles()}
      />{" "}
      {!isMobile && (
        <div>
          <Button
            onClick={() => setCsvExportVisible(true)}
            className="download-button"
          >
            {t("commissioning.export_harvest_csv")}
          </Button>
          <ToolTipIcon title={t("tooltip.csv_export_harvest")} />
        </div>
      )}
      {!isMobile && (
        <ExplainerText title={t("common.info")}>
          {t("explainers.documentationharvest")}
        </ExplainerText>
      )}
    </div>
  );
}
