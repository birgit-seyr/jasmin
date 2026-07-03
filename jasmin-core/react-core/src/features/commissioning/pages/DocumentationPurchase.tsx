import type { FormInstance } from "antd";
import { Button } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningPurchaseBulkSetAsExpectedCreate,
  commissioningPurchaseCreate,
  commissioningPurchaseDestroy,
  commissioningPurchasePartialUpdate,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  Purchase,
  PurchaseBulkSetAsExpectedItem,
} from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { ExportCsvPurchase } from "@features/commissioning/modals";
import { WeekSelector } from "@shared/selectors";
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
import {
  BulkActionButton,
  ExplainerText,
  PastWarningMessage,
} from "@shared/ui";
import { AddShareArticleEntry } from "@features/commissioning/components";
import {
  useCurrency,
  useNoteColumn,
  useNumberFormat,
  useTableRowSelection,
  useUnitOptions,
} from "@hooks/index";
import {
  useAmountUnitSizeColumns,
  useDocumentationSummaryPage,
  useSellerColumn,
  useShareArticleColumn,
  useShareArticles,
  useStorageColumns,
  useStorages,
} from "@features/commissioning/hooks";
import type { DocumentationSummaryRecord } from "@features/commissioning/hooks/useDocumentationSummaryPage";
import type { StorageOption } from "@features/commissioning/hooks/useStorages";

const currentWeek = dayjs().isoWeek();

const shareArticleFilters = {
  is_active: true,
  is_purchased: true,
};

export default function DocumentationPurchase() {
  const { isStaff } = useRoles();
  // Shared week/is_past state + summary query + invalidate wiring; the
  // purchase-specific storage columns / seller / mutation endpoints /
  // customSave stay below. Week-scoped (no day_number).
  const {
    selectedYear,
    setSelectedYear,
    selectedWeek,
    setSelectedWeek,
    isPast,
    rawData,
    isFetching,
    invalidateData,
    onSaveSuccess,
    onDeleteSuccess,
  } = useDocumentationSummaryPage({ model: "purchase", withDay: false });
  const [csvExportVisible, setCsvExportVisible] = useState(false);

  const permissions = useMemo(
    () => ({
      ...gatedByPermission(isStaff && !isPast),
      canDeleteRecord: (record: TableRecord) => {
        if (record.key === -1 || !record.id) return true;
        const r = record as Record<string, unknown>;
        if (
          r.theoretical_purchase_amount != null &&
          r.theoretical_purchase_amount != 0
        )
          return false;
        if (
          r.additional_theoretical_purchase_amount != null &&
          r.additional_theoretical_purchase_amount != 0
        )
          return false;
        return true;
      },
    }),
    [isStaff, isPast],
  );

  const { storages, storagesCount } = useStorages();
  const { storageColumns } = useStorageColumns();
  const { noteColumn } = useNoteColumn();
  const { shareArticleColumn } = useShareArticleColumn({
    filters: shareArticleFilters,
    showFruitsAndVegs: true,
    articleDefaults: "purchase",
  });

  const { getUnitLabel } = useUnitOptions();
  const { currencySymbol } = useCurrency();
  const { format } = useNumberFormat();

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

  const { t } = useTranslation();

  const { refetch: refetchShareArticles } =
    useShareArticles(shareArticleFilters);

  const sellerColumn = useSellerColumn({
    overrides: { align: "left", sortable: true },
  });

  // EditableTable's ``initialData`` resyncs from the summary query (in the
  // hook above); writes call ``invalidateData()`` to trigger a refetch.
  const data = useMemo<TableRecord[]>(() => {
    // Directional cast at the orval boundary: raw rows lack the table-only
    // ``key`` until the map below adds it.
    const items = (rawData ?? []) as DocumentationSummaryRecord[];
    return items
      .filter(
        (item) =>
          !!(
            item.theoretical_purchase_amount ||
            item.additional_theoretical_purchase_amount ||
            item.purchase_amount
          ),
      )
      .map((item) => ({
        ...item,
        key: item.id ?? "",
      }));
  }, [rawData]);

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => {
      const storageFields = storages.map(
        (storage: StorageOption) => `storage_${storage.id}`,
      );
      const hasAtLeastOneStorage = storageFields.some(
        (field) => transformedData[field] === true,
      );

      if (!hasAtLeastOneStorage) {
        throw new Error(
          t("validation.at_least_one_storage_required") ||
            "At least one storage must be selected",
        );
      }
      const amount =
        transformedData.amount === null ||
        transformedData.amount === undefined ||
        transformedData.amount === ""
          ? 0
          : transformedData.amount;
      return {
        ...transformedData,
        amount,
        year: selectedYear,
        delivery_week: selectedWeek ?? currentWeek,
      };
    },
    [selectedYear, selectedWeek, storages, t],
  );

  const customEdit = useCallback((record: TableRecord, form: FormInstance) => {
    if (record.key === -1) {
      const defaultValues = { size: "M" };
      form.setFieldsValue(defaultValues);
      return { ...record, ...defaultValues } as TableRecord;
    }

    const formValues: Record<string, unknown> = {};
    const recordUpdates: Record<string, unknown> = {};
    const r = record as Record<string, unknown>;

    if (r.purchase_amount !== null && r.purchase_amount !== undefined) {
      formValues.amount = r.purchase_amount;
      recordUpdates.amount = r.purchase_amount;
    }

    if (Object.keys(formValues).length > 0) {
      form.setFieldsValue(formValues);
    }

    return { ...record, ...recordUpdates } as TableRecord;
  }, []);

  const {
    selectedRowKeys,
    onSelectedRowsChange: handleRowSelectionChange,
    rowSelection: rowSelectionConfig,
  } = useTableRowSelection(
    (record: TableRecord) =>
      record.key === -1 ||
      record.harvest_amount != null ||
      record.theoretical_harvest_amount === 0,
  );

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<Purchase & TableRecord>({
        create: (payload) => commissioningPurchaseCreate(payload),
        update: (id, payload) =>
          commissioningPurchasePartialUpdate(id, payload),
        delete: (id) => commissioningPurchaseDestroy(id),
      }),
    [],
  );

  const columns = useMemo<EditableColumnConfig<TableRecord>[]>(
    () => [
      {
        ...shareArticleColumn,
        disabled: (record: TableRecord) => record.key != -1,
      },
      ...(amountUnitSizeColumns as unknown as EditableColumnConfig<TableRecord>[]),
      {
        title: <>{t("commissioning.expected_purchase")}</>,
        dataIndex: "theoretical_purchase",
        key: "theoretical_purchase",
        inputType: "text",
        required: false,
        width: "8em",
        align: "center",
        disabled: true,
        readOnly: true,
        render: (_: unknown, record: Record<string, unknown>) => {
          const theoretical_amount =
            (record.theoretical_purchase_amount as number) || 0;
          const additional_amount =
            (record.additional_theoretical_purchase_amount as number) || 0;
          const totalAmount = theoretical_amount + additional_amount;
          return totalAmount > 0 ? format(totalAmount, 2) : "";
        },
      },
      {
        title: <>{t("commissioning.actual_purchase")}</>,
        dataIndex: "amount",
        key: "amount",
        inputType: "positive_decimal2",
        required: false,
        width: "8em",
        align: "center",
        disabled: false,
        readOnly: false,
        render: (_: unknown, record: Record<string, unknown>) => {
          return record.purchase_amount != null
            ? format(Number(record.purchase_amount), 2)
            : "";
        },
      },
      ...(storagesCount > 1
        ? (storageColumns as unknown as EditableColumnConfig<TableRecord>[])
        : []),
      sellerColumn,
      {
        title: <>{t("commissioning.price_per_unit")}</>,
        dataIndex: "price_per_unit",
        key: "price_per_unit",
        inputType: "positive_decimal2",
        required: false,
        width: "8em",
        suffix: currencySymbol,
        render: (_: unknown, record: Record<string, unknown>) => (
          <>
            {record.price_per_unit
              ? `${format(Number(record.price_per_unit), 2)} ${currencySymbol}/${getUnitLabel(
                  record.unit as string,
                )}`
              : ""}
          </>
        ),
      },
      {
        ...noteColumn,
        inputType: "optional",
        width: "25em",
      },
    ],
    [
      shareArticleColumn,
      amountUnitSizeColumns,
      t,
      format,
      storagesCount,
      storageColumns,
      sellerColumn,
      currencySymbol,
      getUnitLabel,
      noteColumn,
    ],
  );

  const uniqueCheckFields = useMemo(() => {
    const baseFields = ["share_article", "unit", "size"];
    const storageFields = storages.map(
      (storage: StorageOption) => `storage_${storage.id}`,
    );
    return [...baseFields, ...storageFields];
  }, [storages]);

  return (
    <div>
      <h1>{t("commissioning.documentation_purchase")}</h1>

      <WeekSelector
        selectedYear={selectedYear}
        setSelectedYear={setSelectedYear}
        selectedWeek={selectedWeek}
        setSelectedWeek={setSelectedWeek}
      />

      {isPast && (
        <PastWarningMessage>{t("table.past_week_readonly")}</PastWarningMessage>
      )}
      {!isPast && (
        <div className="bulk-actions-header">
          <strong>{t("commissioning.for_selected")}</strong>
        </div>
      )}
      {!isPast && (
        <div className="button-row-spaced">
          {storages.map((storage: StorageOption) => (
            <BulkActionButton
              key={storage.id}
              selectedIds={selectedRowKeys}
              apiFunction={(payload) => {
                const selectedData: PurchaseBulkSetAsExpectedItem[] = (
                  payload.ids as string[]
                ).map((id) => {
                  const row = data.find((item) => item.id === id);
                  const rowData = row as Record<string, unknown> | undefined;
                  return {
                    id: rowData?.share_article as string,
                    theoretical_purchase_amount:
                      rowData?.theoretical_purchase_amount as number,
                    theoretical_purchase_unit: rowData?.unit as string,
                    theoretical_purchase_size: rowData?.size as string,
                    year: selectedYear,
                    delivery_week: selectedWeek ?? currentWeek,
                    storage: storage.id!,
                  };
                });
                return commissioningPurchaseBulkSetAsExpectedCreate({
                  selectedData,
                });
              }}
              buttonText={t("commissioning.set_as_expected_purchase_for", {
                storage: storage.name,
              })}
              buttonProps={{ type: "primary" }}
              disabled={
                selectedRowKeys.length === 0 ||
                selectedRowKeys.some((key) => {
                  const row = data.find((item) => item.id === key);
                  const rowData = row as Record<string, unknown> | undefined;
                  return (
                    rowData?.theoretical_purchase_amount == null ||
                    rowData?.theoretical_purchase_amount === 0 ||
                    (rowData?.purchase_amount as number) > 0
                  );
                })
              }
              refreshData={invalidateData}
              onSuccess={invalidateData}
            />
          ))}
        </div>
      )}

      <EditableTable
        key={`${selectedYear}-${selectedWeek}`}
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
        rowSelection={!isPast ? rowSelectionConfig : undefined}
        onSelectedRowsChange={handleRowSelectionChange}
        selectedRowKeys={selectedRowKeys}
        uniqueCheck={uniqueCheckFields}
        uniqueCheckMessage={t("validation.unique.documentation_purchase")}
      />
      <ExportCsvPurchase
        open={csvExportVisible}
        onClose={() => setCsvExportVisible(false)}
      />

      <AddShareArticleEntry
        disabled={isPast}
        defaultValues={{ is_purchased: true }}
        onSuccess={() => refetchShareArticles()}
      />
      <div>
        <Button
          onClick={() => setCsvExportVisible(true)}
          className="download-button"
        >
          {t("commissioning.csv_export_purchase") || "CSV Export"}
        </Button>
      </div>
      <ExplainerText title={t("common.info")}>
        {t("explainers.purchase")}
      </ExplainerText>
    </div>
  );
}
