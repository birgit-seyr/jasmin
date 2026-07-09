import { useQueryClient } from "@tanstack/react-query";
import type { FormInstance } from "antd";
import { Button, Modal } from "antd";
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningCrateContentsInvoiceCreate,
  commissioningCrateContentsInvoiceDestroy,
  commissioningCrateContentsInvoicePartialUpdate,
  commissioningInvoiceContentsCreate,
  commissioningInvoiceContentsDestroy,
  commissioningInvoiceContentsPartialUpdate,
  getCommissioningInvoicesRetrieveQueryKey,
  useCommissioningInvoicesRetrieve,
} from "@shared/api/generated/commissioning/commissioning";
import type { CommissioningCrateContentsInvoiceDestroyParams } from "@shared/api/generated/models/commissioningCrateContentsInvoiceDestroyParams";
import type { CrateContentInvoiceReseller } from "@shared/api/generated/models/crateContentInvoiceReseller";
import type { CrateInvoiceContentWriteRequest } from "@shared/api/generated/models/crateInvoiceContentWriteRequest";
import type { InvoiceResellerContent } from "@shared/api/generated/models/invoiceResellerContent";
import {
  computeLineNetto,
  itemLineNetto,
  type LineNettoInput,
} from "@shared/utils/lineNetto";
import { useCurrency, useDateFormat, useDefaultTaxRates, useNumberFormat, useTenant, useTimeFormat, useUnitOptions } from '@hooks/index';
import { useAmountUnitSizeColumns, useCratesColumns, useShareArticleColumn } from '@features/commissioning/hooks';
import { FinalizedNotice } from '@features/commissioning/components';
// InvoicePDFGenerator statically imports @react-pdf/renderer (it
// renders ``<PDFViewer>`` for inline preview). Lazy-loading it here
// means the modal-bearing pages (Invoices.tsx, Orders.tsx via
// OrderInfoPanel) don't pull the ~484 KB gzip PDF chunk into their
// eager bundles. Vite will emit InvoicePDFGenerator + its transitive
// deps as a separate chunk that only loads when this Suspense
// boundary first renders the component.
const InvoicePDFGenerator = lazy(
  () => import("../pdfs/forResellers/InvoicePDFGenerator"),
);
import {
  computeTaxBreakdown,
  taxBreakdownFromBackend,
  totalsFromBreakdown,
  type LineItemBase,
  type TaxBreakdownItem,
} from "../pdfs/forResellers/pdfBase";
import { EditableTable, gatedByPermission, wrapApiFunctions } from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { DiffCell, ToolTipIcon } from "@shared/ui";
import { useRoles } from "@shared/auth";

type InvoiceContentRecord = InvoiceResellerContent & TableRecord;
type CrateContentRecord = CrateContentInvoiceReseller & TableRecord;

interface InvoiceModalProps {
  visible: boolean;
  onClose: () => void;
  invoiceId: string | null;
}

export default function InvoiceModal({
  visible,
  onClose,
  invoiceId,
}: InvoiceModalProps) {
  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const queryClient = useQueryClient();
  const { getSetting } = useTenant();
  const { formatDateTime } = useTimeFormat();
  const { formatDate } = useDateFormat();
  const { articles: defaultTaxRateArticles } = useDefaultTaxRates();

  // ``isFetching`` (not ``isLoading``): drives the EditableTable grid spinner.
  // With staleTime:0 a reopened (cached) invoice has ``isLoading === false``,
  // so only ``isFetching`` shows the refresh while the retrieve refetches.
  const { data: invoiceData, isFetching: loading } =
    useCommissioningInvoicesRetrieve(invoiceId!, {
      query: { enabled: visible && !!invoiceId },
    });

  const lineItems = useMemo(
    () => (invoiceData?.line_items ?? []) as InvoiceContentRecord[],
    [invoiceData],
  );
  const lineItemsCrates = useMemo(
    () => (invoiceData?.crate_items ?? []) as unknown as CrateContentRecord[],
    [invoiceData],
  );
  const isFinalized = invoiceData?.is_finalized ?? false;

  // Mirror the table rows into local state so the invoice totals + tax
  // breakdown below can be derived LIVE from the current rows. An in-place
  // edit (update path) deliberately does NOT invalidate the retrieve query
  // (that would re-sort the edited row, since the backend has no stable
  // ordering on the items), so the cached invoice-level aggregates would
  // otherwise go stale. Re-seed whenever the server data changes (create /
  // delete DO invalidate); ``onDataChange`` keeps it current during edits.
  const [liveLineItems, setLiveLineItems] =
    useState<InvoiceContentRecord[]>(lineItems);
  const [liveCrateItems, setLiveCrateItems] =
    useState<CrateContentRecord[]>(lineItemsCrates);
  useEffect(() => setLiveLineItems(lineItems), [lineItems]);
  useEffect(() => setLiveCrateItems(lineItemsCrates), [lineItemsCrates]);
  const permissions = useMemo(
    () => gatedByPermission(!isFinalized && isOffice),
    [isFinalized, isOffice],
  );

  const invalidateInvoice = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningInvoicesRetrieveQueryKey(invoiceId!),
    });
  }, [queryClient, invoiceId]);

  // Invalidate the invoice query on CREATE so the new row lands with its
  // server id. UPDATE deliberately skips invalidation so an edited row doesn't
  // spring to a new sort position mid-flow — the office sees the new values via
  // local state, and the invoice totals / tax-breakdown now recompute LIVE from
  // the table rows (see ``taxBreakdown`` above), so they no longer go stale.
  // DELETE invalidates so the row vanishes from the table.
  const handleSaveSuccess = useCallback(
    (_record: TableRecord, action: "create" | "update") => {
      if (action === "create") {
        invalidateInvoice();
      }
    },
    [invalidateInvoice],
  );

  const handleDeleteSuccess = useCallback(() => {
    invalidateInvoice();
  }, [invalidateInvoice]);

  const { getUnitLabel } = useUnitOptions();
  // Tier thresholds for live price-per-unit on amount entry. Single-tier
  // mode (``[1]``) when the tenant hasn't configured tiers — only
  // ``price_1`` is ever picked, no quantity-based escalation.
  const finalTiers = useMemo<number[]>(() => {
    const fromSetting = getSetting("used_tiers_for_offers") as
      | number[]
      | undefined;
    return fromSetting && fromSetting.length > 0 ? fromSetting : [1];
  }, [getSetting]);
  // Invoices include both regular and extra share articles.
  const { shareArticleColumn, handleUnitChange, handleAmountChange } =
    useShareArticleColumn({
      filters: { get_price_info: true, include_extra: true },
      articleDefaults: "reseller",
      finalTiers,
    });
  const { currencySymbol, formatCurrency } = useCurrency();
  const { format } = useNumberFormat();

  const { amountUnitSizeColumns } = useAmountUnitSizeColumns({
    overrides: {
      unit: {
        onFieldChange: handleUnitChange,
      },
      amount: {
        title: t("commissioning.ordered_amount"),
        width: "6em",
        inputType: "positive_decimal3",
        onFieldChange: handleAmountChange,
        render: (value: unknown, record: InvoiceContentRecord) => {
          const numValue = Number(value);
          if (isNaN(numValue) || numValue === 0) return "";
          if (!record.unit) return format(numValue, 2);
          return record.unit === "KG"
            ? format(numValue, 2)
            : format(numValue, 1);
        },
      },
    },
  });

  const { cratesColumns: columnsCrates, crates: crateOptions } =
    useCratesColumns();

  // Filter out crate-types already used on this invoice — same
  // pattern as Orders.tsx (useColumnsOrders.filteredColumnsCrates).
  // Without this the office could pick the same crate twice and hit
  // the (invoice, crate_type) unique constraint at save.
  const filteredColumnsCrates = useMemo(() => {
    const usedCrateTypes = new Set(
      lineItemsCrates.map(
        (item) => (item as Record<string, unknown>).crate_type,
      ),
    );
    const availableOptions = crateOptions.filter(
      (opt) => !usedCrateTypes.has(opt.value as string),
    );
    return columnsCrates.map((col) =>
      col.key === "crate_type_name"
        ? { ...col, options: availableOptions }
        : col,
    );
  }, [columnsCrates, crateOptions, lineItemsCrates]);

  // When no unused crate-types remain, disable the add-row button on
  // the crates table (edit/delete still allowed for existing rows).
  const cratesPermissions = useMemo(() => {
    const usedCrateTypes = new Set(
      lineItemsCrates.map(
        (item) => (item as Record<string, unknown>).crate_type,
      ),
    );
    const hasAvailable = crateOptions.some(
      (opt) => !usedCrateTypes.has(opt.value as string),
    );
    const baseCanWrite = !isFinalized && isOffice;
    return {
      canAdd: baseCanWrite && hasAvailable,
      canEdit: baseCanWrite,
      canDelete: baseCanWrite,
    };
  }, [crateOptions, lineItemsCrates, isFinalized, isOffice]);

  const columnsPrices = useMemo<EditableColumnConfig<InvoiceContentRecord>[]>(
    () => [
      {
        title: <>{t("commissioning.rabatt")}</>,
        dataIndex: "rabatt",
        key: "rabatt",
        inputType: "positive_integer",
        required: false,
        suffix: "%",
        align: "center",
        width: "7em",
        render: (_, record) => (
          <DiffCell
            value={record.rabatt ? `${record.rabatt} %` : ""}
            differs={record.rabatt_differs}
            original={record.original_rabatt}
            originalSuffix=" %"
          />
        ),
      },
      {
        title: <>{t("commissioning.line_netto")}</>,
        dataIndex: "line_netto",
        key: "line_netto",
        inputType: "positive_decimal2",
        required: false,
        readOnly: true,
        disabled: true,
        align: "right",
        width: "8em",
        render: (_, record) => {
          const finalPrice = itemLineNetto(record as unknown as LineNettoInput);
          return (
            <span>{formatCurrency(finalPrice)}</span>
          );
        },
      },
      {
        title: <span className="text-xs">{t("commissioning.ust")}</span>,
        dataIndex: "tax_rate",
        key: "tax_rate",
        inputType: "positive_integer",
        required: false,
        align: "center",
        width: "6em",
        render: (_, record) => (
          <span className="text-xs">
            {record.tax_rate ? `${format(Number(record.tax_rate), 2)} %` : ""}
          </span>
        ),
      },
    ],
    [t, formatCurrency, format],
  );

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => {
      return {
        ...transformedData,
        invoice: invoiceId,
      };
    },
    [invoiceId],
  );

  const customSaveCrates = useCallback(
    (transformedData: Record<string, unknown>) => {
      return {
        ...transformedData,
        invoice_id: invoiceData?.id,
      };
    },
    [invoiceData],
  );

  const customEdit = useCallback(
    (record: TableRecord, form: FormInstance) => {
      if (record.key === -1) {
        const defaultValues = {
          size: "M",
          unit: "KG",
          tax_rate: defaultTaxRateArticles,
        };
        form.setFieldsValue(defaultValues);
        return { ...record, ...defaultValues } as TableRecord;
      }
      return record;
    },
    [defaultTaxRateArticles],
  );

  const customDeleteCrates = useCallback(
    (record: TableRecord) => {
      return {
        crate_type: (record as Record<string, unknown>).crate_type,
        invoice_id: invoiceId,
      };
    },
    [invoiceId],
  );

  const apiFunctionsContents = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<InvoiceContentRecord>({
        create: (data) => commissioningInvoiceContentsCreate(data),
        update: (id, data) => commissioningInvoiceContentsPartialUpdate(id, data),
        delete: (id) => commissioningInvoiceContentsDestroy(id),
      }),
    [],
  );

  const apiFunctionsCrates = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<CrateInvoiceContentWriteRequest & TableRecord>({
        create: (data) => commissioningCrateContentsInvoiceCreate(data),
        update: (id, data) =>
          commissioningCrateContentsInvoicePartialUpdate(
            id,
            data as unknown as CrateContentInvoiceReseller,
          ),
        delete: (id, data) =>
          commissioningCrateContentsInvoiceDestroy(
            id,
            data as unknown as CommissioningCrateContentsInvoiceDestroyParams,
          ),
      }),
    [],
  );

  const columns = useMemo<EditableColumnConfig<InvoiceContentRecord>[]>(
    () => [
      {
        ...shareArticleColumn,
        disabled: (record) => record.key !== -1,
      },
      {
        title: <>{t("commissioning.sort")}</>,
        dataIndex: "sort",
        key: "sort",
        inputType: "optional",
        required: false,
        width: "8em",
      },
      ...amountUnitSizeColumns.map((col) => {
        // `differField` / `originalField` are runtime-derived keys, so
        // TS can't statically narrow them — index access still needs a
        // cast even with a typed record.
        const differField = `${col.dataIndex}_differs`;
        const originalField = `original_${col.dataIndex}`;

        return {
          ...col,
          render: (value: unknown, record: InvoiceContentRecord) => (
            <DiffCell
              value={
                (col as EditableColumnConfig).render
                  ? (col as EditableColumnConfig).render!(
                      value,
                      record as TableRecord,
                      0,
                    )
                  : (value as string)
              }
              differs={record[differField] as boolean | undefined}
              original={record[originalField]}
            />
          ),
        };
      }),
      {
        title: <>{t("commissioning.single_price")}</>,
        dataIndex: "price_per_unit",
        key: "price_per_unit",
        inputType: "decimal2",
        required: false,
        suffix: currencySymbol,
        align: "center",
        width: "11em",
        render: (_, record) => (
          <DiffCell
            value={
              record.price_per_unit
                ? `${formatCurrency(Number(record.price_per_unit))}/${getUnitLabel(
                    record.unit,
                  )}`
                : ""
            }
            differs={record.price_per_unit_differs}
            original={record.original_price_per_unit}
            formatOriginal={(o) => formatCurrency(Number(o))}
          />
        ),
      },
      ...columnsPrices,
    ],
    [
      shareArticleColumn,
      amountUnitSizeColumns,
      columnsPrices,
      getUnitLabel,
      t,
      currencySymbol,
      formatCurrency,
    ],
  );

  const invoiceAny = invoiceData as Record<string, unknown> | undefined;
  // Finalized invoices are read-only legal documents → show the backend's
  // authoritative netto/USt/brutto verbatim. Editable invoices derive the
  // summary from the LIVE rows, recomputing each line's net from its current
  // amount/price (the cached ``line_netto`` is stale right after an in-place
  // edit), so the totals stay in sync without invalidating + re-sorting.
  const taxBreakdown = useMemo<TaxBreakdownItem[]>(() => {
    if (isFinalized) {
      return taxBreakdownFromBackend(invoiceAny?.tax_breakdown) ?? [];
    }
    const withFreshNetto = (rows: TableRecord[]) =>
      rows.map((row) => ({
        ...row,
        line_netto: computeLineNetto(row as LineNettoInput),
      }));
    return computeTaxBreakdown(
      withFreshNetto(liveLineItems) as unknown as LineItemBase[],
      withFreshNetto(liveCrateItems) as unknown as LineItemBase[],
    );
  }, [isFinalized, invoiceAny?.tax_breakdown, liveLineItems, liveCrateItems]);
  const liveTotals = useMemo(
    () => totalsFromBreakdown(taxBreakdown),
    [taxBreakdown],
  );
  const totalNetto = isFinalized
    ? Number(invoiceAny?.sum_netto ?? 0)
    : liveTotals.netto;
  const totalBrutto = isFinalized
    ? Number(invoiceAny?.sum_brutto ?? 0)
    : liveTotals.brutto;

  return (
    <Modal
      title={
        invoiceData
          ? `${t("commissioning.invoice_details")} ${invoiceData.prefix}-${invoiceData.invoice_number}`
          : ""
      }
      open={visible}
      onCancel={onClose}
      width={1200}
      footer={
        <div className="flex-end gap-8">
          {isFinalized && (
            <Suspense
              fallback={<Button loading size="middle" type="primary" />}
            >
              <InvoicePDFGenerator
                invoiceId={invoiceId}
                buttonText={t("commissioning.pdf")}
                buttonSize="middle"
              />
            </Suspense>
          )}
          <Button onClick={onClose} size="middle">
            {t("common.close")}
          </Button>
        </div>
      }
    >
      {invoiceData && (
        <div>
          <div style={{ marginBottom: "1em" }}>
            <p>
              <strong>{t("resellers.reseller")}</strong>{" "}
              {invoiceData.reseller_name}
            </p>
            <p>
              <strong>{t("commissioning.invoice_date")}</strong>{" "}
              {formatDate(invoiceData.invoice_date)}
            </p>
            <p>
              <strong>{t("commissioning.corresponding_delivery_notes")}</strong>{" "}
              {invoiceData.corresponding_delivery_notes}
            </p>
            <p>
              <strong>{t("commissioning.sent_to_resellers_at")}</strong>{" "}
              {invoiceData?.has_been_sent_to_reseller_at
                ? formatDateTime(invoiceData.has_been_sent_to_reseller_at)
                : ""}
            </p>
            <p>
              <strong>{t("commissioning.sent_to_accounting_at")}</strong>{" "}
              {invoiceData?.has_been_sent_to_accounting_at
                ? formatDateTime(invoiceData.has_been_sent_to_accounting_at)
                : ""}
            </p>
          </div>
          {isFinalized && (
            <FinalizedNotice
              label={t("commissioning.invoice_finalized_notice")}
              at={invoiceData.finalized_at}
            />
          )}

          <EditableTable
            key={invoiceId!}
            columns={columns as EditableColumnConfig[]}
            apiFunctions={apiFunctionsContents}
            initialData={lineItems}
            permissions={permissions}
            loading={loading}
            customSave={customSave}
            customEdit={customEdit}
            uniqueCheck={["share_article", "size", "unit"]}
            uniqueCheckMessage={t(
              "validation.unique.share_article_unit_size_must_be_unique",
            )}
            onDataChange={(d) => setLiveLineItems(d as InvoiceContentRecord[])}
            onSaveSuccess={handleSaveSuccess}
            onDeleteSuccess={handleDeleteSuccess}
          />
          <div
            style={{
              marginTop: "4em",
              marginBottom: "-1em",
              display: "flex",
              alignItems: "center",
              gap: "0.5em",
            }}
          >
            <h5 style={{ margin: 0 }}>
              {t("commissioning.crates_invoicemodal")}
            </h5>
            <ToolTipIcon title={t("tooltip.crates_used_in_invoice")} />
          </div>
          <EditableTable
            key="crates"
            columns={filteredColumnsCrates as EditableColumnConfig[]}
            apiFunctions={apiFunctionsCrates}
            initialData={lineItemsCrates}
            permissions={cratesPermissions}
            loading={loading}
            customSave={customSaveCrates}
            customDelete={customDeleteCrates}
            uniqueCheck={["crate_type"]}
            uniqueCheckMessage={t("validation.unique.invoice_modal_crate")}
            onDataChange={(d) => setLiveCrateItems(d as CrateContentRecord[])}
            onSaveSuccess={handleSaveSuccess}
            onDeleteSuccess={handleDeleteSuccess}
          />

          <div
            style={{
              marginTop: "1em",
              textAlign: "right",
              fontSize: "0.95em",
            }}
          >
            {taxBreakdown.map((item) => (
              <div key={item.rate} style={{ marginBottom: "0.3em" }}>
                <span style={{ fontWeight: "normal" }}>
                  {t("commissioning.netto")} ({item.rate}%):{" "}
                  {formatCurrency(item.netto)}
                </span>
                <span style={{ marginLeft: "1.5em", fontWeight: "normal" }}>
                  {t("commissioning.ust")} ({item.rate}%):{" "}
                  {formatCurrency(item.tax)}
                </span>
              </div>
            ))}
          </div>

          <div
            style={{
              marginTop: "1em",
              paddingTop: "0.5em",
              borderTop: "1px solid var(--color-border)",
              textAlign: "right",
              fontSize: "1em",
              fontWeight: "bold",
            }}
          >
            {t("commissioning.total_sum_netto_invoice_details")}{" "}
            {formatCurrency(totalNetto)}
          </div>
          <div
            style={{
              paddingTop: "0.5em",
              textAlign: "right",
              fontSize: "1em",
            }}
          >
            {t("commissioning.total_sum_ust_invoice_details")}{" "}
            {formatCurrency(totalBrutto - totalNetto)}
          </div>

          <div
            style={{
              marginTop: "0.5em",
              textAlign: "right",
              fontSize: "1.1em",
              fontWeight: "bold",
            }}
          >
            {t("commissioning.total_sum_brutto_invoice_details")}{" "}
            {formatCurrency(totalBrutto)}
          </div>
        </div>
      )}
    </Modal>
  );
}
