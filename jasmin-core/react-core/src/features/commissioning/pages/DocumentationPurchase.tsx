import type { FormInstance } from "antd";
import { Button } from "antd";
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
import { OrganicStatusEnum } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { ExportCsvPurchase } from "@features/commissioning/modals";
import { WeekSelector } from "@shared/selectors";
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
import {
  BulkActionButton,
  ExplainerText,
  MobileStack,
  PastWarningMessage,
} from "@shared/ui";
import { AddShareArticleEntry } from "@features/commissioning/components";
import {
  currentWeek,
  useCurrency,
  useNoteColumn,
  useNumberFormat,
  useTableRowSelection,
  useUnitOptions,
} from "@hooks/index";
import {
  useAmountUnitSizeColumns,
  useOrganicStatusColumn,
  useSellerColumn,
  useShareArticleColumn,
  useShareArticles,
  useStorageDocumentationPage,
} from "@features/commissioning/hooks";
import type { DocumentationSummaryRecord } from "@features/commissioning/hooks/useDocumentationSummaryPage";

const shareArticleFilters = {
  is_active: true,
  is_purchased: true,
};

export default function DocumentationPurchase() {
  const { isStaff } = useRoles();

  // A storage-matched purchase row is worth showing only if it carries a
  // theoretical, additional-theoretical, or actual purchase amount.
  const rowHasData = useCallback(
    (item: DocumentationSummaryRecord) =>
      !!(
        item.theoretical_purchase_amount ||
        item.additional_theoretical_purchase_amount ||
        item.purchase_amount
      ),
    [],
  );

  // Shared week/is_past + summary query + storage selector/filter +
  // storage-stamped customSave + remount key. Purchase-specific bits (columns,
  // seller/organic, mutation endpoints, bulk action) stay below. Week-scoped
  // (no day_number).
  const {
    selectedYear,
    setSelectedYear,
    selectedWeek,
    setSelectedWeek,
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
    model: "purchase",
    withDay: false,
    rowHasData,
  });
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

  const { noteColumn } = useNoteColumn();
  const { shareArticleColumn } = useShareArticleColumn({
    filters: shareArticleFilters,
    showFruitsAndVegs: true,
    articleDefaults: "purchase",
  });

  const { getUnitLabel } = useUnitOptions();
  const { currencySymbol, formatCurrency } = useCurrency();
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
  const organicStatusColumn = useOrganicStatusColumn();

  const { refetch: refetchShareArticles } =
    useShareArticles(shareArticleFilters);

  const sellerColumn = useSellerColumn({
    overrides: { align: "left", sortable: true, required: true },
  });

  const customEdit = useCallback(
    (record: TableRecord, form: FormInstance) => {
      if (record.key === -1) {
        const defaultValues: Record<string, unknown> = { size: "M" };
        // When the tenant is organic-certified (the column is shown), default a
        // new purchase row to ``organic`` so the common case needs no toggle.
        if (organicStatusColumn.length > 0) {
          defaultValues.organic_status = OrganicStatusEnum.organic;
        }

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
    },
    [organicStatusColumn],
  );

  const {
    selectedRowKeys,
    onSelectedRowsChange: handleRowSelectionChange,
    rowSelection: rowSelectionConfig,
  } = useTableRowSelection((record: TableRecord) => record.key === -1);

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
      sellerColumn,
      // Organic status of the purchase — only when the tenant is itself
      // certified. ``organic`` / ``in_conversion`` are rejected on save unless
      // the seller holds a certificate valid for the purchase's week (backend).
      ...organicStatusColumn,
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
              ? `${formatCurrency(Number(record.price_per_unit))}/${getUnitLabel(
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
      sellerColumn,
      organicStatusColumn,
      currencySymbol,
      formatCurrency,
      getUnitLabel,
      noteColumn,
    ],
  );

  return (
    <div>
      <h1>{t("commissioning.documentation_purchase")}</h1>

      <MobileStack>
        <WeekSelector
          selectedYear={selectedYear}
          setSelectedYear={setSelectedYear}
          selectedWeek={selectedWeek}
          setSelectedWeek={setSelectedWeek}
        />
        <StorageSelector
          selectedStorage={selectedStorage}
          setSelectedStorage={setSelectedStorage}
        />
      </MobileStack>

      {isPast && (
        <PastWarningMessage>{t("table.past_week_readonly")}</PastWarningMessage>
      )}
      {!isPast && (
        <div className="bulk-actions-header">
          <strong>{t("commissioning.for_selected")}</strong>
        </div>
      )}
      {!isPast && selectedStorage && (
        <div className="button-row-spaced">
          <BulkActionButton
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
                  storage: selectedStorage,
                };
              });
              return commissioningPurchaseBulkSetAsExpectedCreate({
                selectedData,
              });
            }}
            buttonText={t("commissioning.set_as_expected_purchase_for", {
              storage:
                storages.find((s) => s.id === selectedStorage)?.name ?? "",
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
        </div>
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
        permissions={permissions}
        rowSelection={!isPast ? rowSelectionConfig : undefined}
        onSelectedRowsChange={handleRowSelectionChange}
        selectedRowKeys={selectedRowKeys}
        uniqueCheck={["share_article", "unit", "size"]}
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
          {t("commissioning.csv_export_purchase")}
        </Button>
      </div>
      <ExplainerText title={t("common.info")}>
        {t("explainers.purchase")}
      </ExplainerText>
    </div>
  );
}
