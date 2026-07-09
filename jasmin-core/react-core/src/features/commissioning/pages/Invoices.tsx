import {
  CalendarOutlined,
  CheckOutlined,
  DownloadOutlined,
  TableOutlined,
} from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Card, Flex, Radio, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningBulkCreateDocumentsFromOrdersCreate,
  commissioningBulkCreateSummaryInvoiceFromOrdersCreate,
  commissioningBulkDeleteDocumentsCreate,
  commissioningBulkFinalizeDocumentsCreate,
  getCommissioningOrdersOverviewListQueryKey,
  useCommissioningInvoicesCreateStornoCreate,
  useCommissioningOrdersOverviewList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  BulkOperationResponse,
  CombinedOrderOverview,
  CommissioningOrdersOverviewListParams,
} from "@shared/api/generated/models";
import { InvoiceModal } from "@features/commissioning/modals";
import StornoInvoiceModal from "@features/commissioning/modals/StornoInvoiceModal";
// ``InvoicePDFButtons`` is light (no @react-pdf import) — safe to
// import from the barrel. The barrel re-exports both heavy and light
// modules though, and Vite's tree-shaking through the barrel isn't
// perfect for side-effectful files, so for the helper we import it
// directly from its dedicated file. That file has no top-level
// @react-pdf static import, which is what keeps the ~484 KB gzip
// PDF chunk out of Invoices.tsx's eager bundle.
import { InvoicePDFButtons } from "@features/commissioning/pdfs";
import { generateAndUploadInvoicePDF } from "@features/commissioning/pdfs/forResellers/generateInvoicePDF";
import DeliveryNotePDFButtons from "@features/commissioning/pdfs/forResellers/DeliveryNotePDFButtons";
import { ResellerSelector, YearSelector } from "@shared/selectors";
import { generatePdfFilename, notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import { EditableTable, READ_ONLY_PERMISSION } from "@shared/tables";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import {
  BulkActionButton,
  ExplainerText,
  ToolTipIcon,
  ViewDetailsButton,
} from "@shared/ui";
import {
  useCurrency,
  useDateFormat,
  useInvalidateAfterTableMutation,
  useNumberFormat,
  useTableRowSelection,
  useTenant,
} from "@hooks/index";

const { Text } = Typography;

const currentYear = dayjs().year();

const GROUPING_MODES = {
  NONE: "none",
  WEEK: "week",
  MONTH: "month",
} as const;

type GroupingMode = (typeof GROUPING_MODES)[keyof typeof GROUPING_MODES];

/** A table row: the generated overview shape + the EditableTable key. */
type InvoiceOverviewRow = CombinedOrderOverview & TableRecord;

interface GroupData {
  key: string;
  name: string;
  items: InvoiceOverviewRow[];
  totalAmount: number;
  canInvoice: boolean;
}

export default function Invoices() {
  const [selectedReseller, setSelectedReseller] = useState<string | null>(null);
  const [groupingMode, setGroupingMode] = useState<GroupingMode>(
    GROUPING_MODES.NONE,
  );
  const {
    selectedRowKeys,
    setSelectedRowKeys,
    onSelectedRowsChange: handleRowSelectionChange,
    rowSelection: rowSelectionConfig,
  } = useTableRowSelection();
  const [selectedYear, setSelectedYear] = useState(currentYear);
  const { t } = useTranslation();
  const { getSetting, tenant, logoUrl, bioLogoUrl } = useTenant();
  const { currencySymbol } = useCurrency();
  const { format } = useNumberFormat();
  const queryClient = useQueryClient();

  const [modalVisible, setModalVisible] = useState(false);
  const [selectedInvoiceId, setSelectedInvoiceId] = useState<string | null>(
    null,
  );

  // Storno modal
  const [stornoModalVisible, setStornoModalVisible] = useState(false);
  const [stornoTargetInvoiceId, setStornoTargetInvoiceId] = useState<
    string | null
  >(null);
  const [stornoTargetLabel, setStornoTargetLabel] = useState("");
  const createStornoMutation = useCommissioningInvoicesCreateStornoCreate();

  const { formatDate } = useDateFormat();

  const listParams = useMemo<CommissioningOrdersOverviewListParams>(
    () => ({
      year: selectedYear,
      ...(selectedReseller ? { reseller: selectedReseller } : {}),
    }),
    [selectedYear, selectedReseller],
  );

  const { data: ordersData, isFetching: loading } =
    useCommissioningOrdersOverviewList(listParams, {
      // Only fetch once a reseller is chosen — don't load the full
      // all-reseller overview on mount / before a selection.
      query: { enabled: Boolean(selectedReseller) },
    });

  // Derive table rows directly from the query result. The table is
  // read-only (READ_ONLY_PERMISSION below), so there's no need to mirror
  // ordersData into local state — that previously cost an extra render
  // cycle and created a stale-state timing trap in tests.
  const data = useMemo<InvoiceOverviewRow[]>(
    () =>
      (ordersData ?? []).map((item) => ({
        ...item,
        key: item.id,
      })),
    [ordersData],
  );

  // Reset row selection when params change
  useEffect(() => {
    setSelectedRowKeys([]);
  }, [selectedYear, selectedReseller, setSelectedRowKeys]);

  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningOrdersOverviewListQueryKey(listParams),
    });
  }, [queryClient, listParams]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

  const handleFinalizeInvoicesSuccess = useCallback(
    async (responseData: BulkOperationResponse) => {
      const invoiceIds = (responseData?.results ?? [])
        .filter((r) => r.success && r.invoice_id)
        .map((r) => r.invoice_id!);

      if (invoiceIds.length === 0) {
        console.warn(
          "[FINALIZE] No invoice IDs found - skipping PDF generation",
        );
        invalidateData();
        return;
      }

      for (const id of invoiceIds) {
        try {
          await generateAndUploadInvoicePDF(
            id,
            t,
            tenant as Record<string, unknown>,
            getSetting,
            logoUrl,
            bioLogoUrl,
          );
        } catch (err) {
          console.error(
            `[FINALIZE] PDF generation FAILED for invoice ${id}:`,
            err,
          );
        }
      }

      invalidateData();
    },
    [t, tenant, getSetting, logoUrl, bioLogoUrl, invalidateData],
  );

  const filteredData = useMemo(() => {
    return data.filter(
      (item) =>
        item.delivery_note_id !== null && item.delivery_note_id !== undefined,
    );
  }, [data]);

  // Invoice ids of the selected rows that carry a finalized invoice — the
  // only ones that can have an e-PDF to bundle into the bulk ZIP.
  const selectedFinalizedInvoiceIds = useMemo(
    () =>
      data
        .filter(
          (item) =>
            selectedRowKeys.includes(item.id) &&
            item.has_finalized_invoice &&
            item.invoice_id,
        )
        .map((item) => item.invoice_id as string),
    [data, selectedRowKeys],
  );

  const handleDownloadBulkZip = useCallback(async () => {
    // Lazy-load the bulk-ZIP flow (and its pdf-lib / fflate dependencies) only
    // on click, keeping them out of the page's eager bundle.
    const { downloadSelectedInvoiceEpdfsZip } = await import(
      "@features/commissioning/pdfs/forResellers/bulkInvoiceZip"
    );
    await downloadSelectedInvoiceEpdfsZip(
      selectedFinalizedInvoiceIds,
      t,
      `${generatePdfFilename([t("commissioning.invoices"), selectedYear])}.zip`,
    );
  }, [selectedFinalizedInvoiceIds, t, selectedYear]);

  const groupedData = useMemo<Record<string, GroupData>>(() => {
    if (groupingMode === GROUPING_MODES.NONE) {
      return {
        ungrouped: {
          key: "ungrouped",
          name: "",
          items: data,
          totalAmount: 0,
          canInvoice: true,
        },
      };
    }

    const groups: Record<string, GroupData> = {};

    filteredData.forEach((item) => {
      if (!item.delivery_note_date) return;

      let groupKey: string;
      let groupName: string;

      switch (groupingMode) {
        case GROUPING_MODES.WEEK: {
          const weekDate = dayjs(item.delivery_note_date);
          groupKey = `${weekDate.year()}-W${String(weekDate.isoWeek()).padStart(2, "0")}`;
          groupName = `${t("commissioning.week")} ${weekDate.isoWeek()}, ${weekDate.year()}`;
          break;
        }
        case GROUPING_MODES.MONTH: {
          const monthDate = dayjs(item.delivery_note_date);
          groupKey = `${monthDate.year()}-${String(monthDate.month() + 1).padStart(2, "0")}`;
          groupName = monthDate.format("MMMM YYYY");
          break;
        }
        default:
          groupKey = "default";
          groupName = t("commissioning.all_items");
      }

      if (!groups[groupKey]) {
        groups[groupKey] = {
          key: groupKey,
          name: groupName,
          items: [],
          totalAmount: 0,
          canInvoice: true,
        };
      }

      groups[groupKey].items.push(item);
      groups[groupKey].totalAmount += parseFloat(item.sum_netto || "0");

      if (item.has_invoice) {
        groups[groupKey].canInvoice = false;
      }
    });

    const sortedGroups: Record<string, GroupData> = {};
    Object.keys(groups)
      .sort()
      .reverse()
      .forEach((key) => {
        sortedGroups[key] = groups[key];
      });

    return sortedGroups;
  }, [filteredData, groupingMode, t, data]);

  const handleOpenModal = useCallback((record: Record<string, unknown>) => {
    setSelectedInvoiceId(record.invoice_id as string);
    setModalVisible(true);
  }, []);

  const handleCloseModal = useCallback(() => {
    setModalVisible(false);
    setTimeout(() => {
      setSelectedInvoiceId(null);
    }, 300);
    invalidateData();
  }, [invalidateData]);

  const handleOpenStornoModal = useCallback(
    (record: Record<string, unknown>) => {
      setStornoTargetInvoiceId(record.invoice_id as string);
      setStornoTargetLabel((record.invoice_number as string) ?? "");
      setStornoModalVisible(true);
    },
    [],
  );

  const handleCreateStorno = useCallback(
    async (reason: string) => {
      if (!stornoTargetInvoiceId) return;
      try {
        const storno = await createStornoMutation.mutateAsync({
          id: stornoTargetInvoiceId,
          data: { reason },
        });
        const stornoId = storno.id;
        setStornoModalVisible(false);
        setStornoTargetInvoiceId(null);

        // Generate and upload PDF/e-PDF for the storno
        if (stornoId) {
          try {
            await generateAndUploadInvoicePDF(
              stornoId,
              t,
              tenant as Record<string, unknown>,
              getSetting,
              logoUrl,
              bioLogoUrl,
            );
          } catch (err) {
            // The storno itself was created + finalized (legal cancellation
            // is done) — only the PDF/e-invoice generation failed. Tell the
            // office so they can regenerate it rather than assume it's there.
            console.error("Failed to generate storno PDF:", err);
            notify.warning(t("commissioning.storno_pdf_failed"));
          }
        }

        invalidateData();
      } catch (err) {
        // Surface the backend's domain error (e.g. "invoice cannot be
        // cancelled") instead of failing silently with the modal still open.
        console.error("Failed to create storno:", err);
        notify.error(getErrorMessage(err, t("commissioning.storno_failed")));
      }
    },
    [
      stornoTargetInvoiceId,
      createStornoMutation,
      invalidateData,
      t,
      tenant,
      getSetting,
      logoUrl,
      bioLogoUrl,
    ],
  );

  const normalColumns = useMemo<EditableColumnConfig<TableRecord>[]>(
    () => [
      {
        title: t("resellers.delivery_note_date"),
        dataIndex: "delivery_note_date",
        key: "delivery_note_date",
        width: "8em",
        inputType: "date",

        sortable: true,

        render: (value: unknown) => formatDate(value as string),
      },
      {
        title: t("resellers.delivery_note_number"),
        dataIndex: "delivery_note_number",
        key: "delivery_note_number",
        width: "12em",
        inputType: "text",

        sortable: true,

        render: (value: unknown, record: Record<string, unknown>) => (
          <span className="dn-number-cell">
            {(record.delivery_note_is_finalized as boolean) ? (
              <>
                <CheckOutlined aria-hidden className="icon-check-success" />
                <span className="sr-only">{t("commissioning.finalized")}</span>
              </>
            ) : (
              <span className="sr-only">
                {t("commissioning.not_finalized")}
              </span>
            )}
            {value as string}
            {(record.delivery_note_id as string | null | undefined) && (
              <DeliveryNotePDFButtons
                deliveryNoteId={record.delivery_note_id as string}
                buttonSize="small"
                buttonType="text"
                buttonText=""
                ariaLabel={t("commissioning.download_delivery_note_n", {
                  number: record.delivery_note_number as string,
                })}
                icon={<DownloadOutlined />}
                className="dn-number-download"
              />
            )}
          </span>
        ),
      },
      {
        title: <>{t("commissioning.order_date_short")}</>,
        dataIndex: "order_date",
        key: "order_date",
        required: true,
        width: "8em",
        align: "left",
        inputType: "date",

        disabled: true,
        sortable: true,

        render: (value: unknown) => formatDate(value as string),
      },
      {
        title: <>{t("resellers.order_number")}</>,
        dataIndex: "order_number",
        key: "order_number",
        required: true,
        width: "12em",
        align: "left",
        inputType: "text",

        disabled: true,
        sortable: true,

        render: (value: unknown, record: Record<string, unknown>) => (
          <>
            {(record.order_is_finalized as boolean) ? (
              <>
                <CheckOutlined aria-hidden className="icon-check-success" />
                <span className="sr-only">{t("commissioning.finalized")}</span>
              </>
            ) : (
              <span className="sr-only">
                {t("commissioning.not_finalized")}
              </span>
            )}
            {value as string}
          </>
        ),
      },
      {
        title: <>{t("commissioning.invoice_date_short")}</>,
        dataIndex: "invoice_date",
        key: "invoice_date",
        required: true,
        width: "8em",
        align: "left",
        inputType: "date",

        disabled: true,
        sortable: true,
        render: (value: unknown) => formatDate(value as string),
      },
      {
        title: t("commissioning.invoice_number"),
        dataIndex: "invoice_number",
        key: "invoice_number",
        width: "12em",
        inputType: "text",

        sortable: true,
        render: (value: unknown, record: Record<string, unknown>) => (
          <>
            {(record.has_finalized_invoice as boolean) ? (
              <>
                <CheckOutlined aria-hidden className="icon-check-success" />
                <span className="sr-only">{t("commissioning.finalized")}</span>
              </>
            ) : (
              <span className="sr-only">
                {t("commissioning.not_finalized")}
              </span>
            )}
            {value as string}
            {record.invoice_cancelled_by ? (
              <Tag color="red" bordered={false}>
                {t("commissioning.storno_short")}
                {record.invoice_storno_number
                  ? ` ${record.invoice_storno_number as string}`
                  : ""}
              </Tag>
            ) : null}
          </>
        ),
      },
      {
        title: t("commissioning.invoice_total_amount_netto"),
        dataIndex: "sum_netto",
        key: "sum_netto",
        width: "8em",
        align: "right",
        sortable: true,
        render: (value: unknown) =>
          `${format(parseFloat((value as string) || "0"), 2)} ${currencySymbol}`,
      },
      {
        title: "",
        dataIndex: "actions",
        key: "actions",
        readOnly: true,
        disabled: true,
        width: "32em",
        render: (_: unknown, record: Record<string, unknown>) => (
          <div className="button-row">
            <>
              {record.has_invoice && (
                <ViewDetailsButton
                  onClick={() => handleOpenModal(record)}
                  label={t("commissioning.view_details_invoice")}
                />
              )}
              {!record.has_finalized_invoice && record.has_invoice && (
                <BulkActionButton
                  selectedIds={record.id ? [record.id as string] : []}
                  apiFunction={(payload) =>
                    commissioningBulkFinalizeDocumentsCreate({
                      ids: payload.ids as string[],
                      model: "invoice" as const,
                    })
                  }
                  buttonText={t("commissioning.finalize_invoice")}
                  buttonProps={{ type: "primary", danger: false }}
                  onSuccess={handleFinalizeInvoicesSuccess}
                  style={{ marginTop: "0em" }}
                />
              )}
              {!record.has_finalized_invoice && record.has_invoice && (
                <BulkActionButton
                  selectedIds={record.id ? [record.id as string] : []}
                  apiFunction={(payload) =>
                    commissioningBulkDeleteDocumentsCreate({
                      ids: payload.ids as string[],
                      model: "invoice" as const,
                    })
                  }
                  buttonText={t("commissioning.delete_invoice")}
                  buttonProps={{ type: "primary", danger: true }}
                  onSuccess={invalidateData}
                  style={{ marginTop: "0em" }}
                />
              )}
              {record.has_finalized_invoice && (
                <InvoicePDFButtons
                  invoiceId={record.invoice_id as string}
                  buttonText={t("commissioning.pdf")}
                  buttonSize="small"
                />
              )}
              {record.has_finalized_invoice && !record.invoice_cancelled_by && (
                <Button
                  size="small"
                  danger
                  onClick={() => handleOpenStornoModal(record)}
                >
                  {t("commissioning.create_storno")}
                </Button>
              )}
              {record.invoice_storno_id && (
                <InvoicePDFButtons
                  invoiceId={record.invoice_storno_id as string}
                  buttonText={`${t("commissioning.storno_pdf")} ${(record as unknown as CombinedOrderOverview).invoice_storno_number || ""}`}
                  buttonSize="small"
                />
              )}
              {!record.has_invoice && (
                <BulkActionButton
                  selectedIds={record.id ? [record.id as string] : []}
                  apiFunction={(payload) =>
                    commissioningBulkCreateDocumentsFromOrdersCreate({
                      ids: payload.ids as string[],
                      model: "invoice" as const,
                    })
                  }
                  buttonText={t("commissioning.create_invoice")}
                  buttonProps={{ type: "primary" }}
                  onSuccess={invalidateData}
                  style={{ marginTop: "0em" }}
                />
              )}
            </>
          </div>
        ),
      },
      {
        title: (
          <>
            {t("resellers.sent_via_email")}{" "}
            <ToolTipIcon title={t("tooltip.sent_via_email")} />
          </>
        ),
        dataIndex: "invoice_has_been_sent_to_reseller",
        inputType: "checkbox",
        key: "invoice_has_been_sent_to_reseller",
        disabled: true,
        sortable: true,
      },
      {
        title: <>{t("resellers.has_been_sent_to_accounting_at")}</>,
        dataIndex: "invoice_has_been_sent_to_accounting",
        key: "invoice_has_been_sent_to_accounting",
        inputType: "checkbox",
        disabled: true,
        sortable: true,
      },
    ],
    [
      t,
      format,
      formatDate,
      currencySymbol,
      handleOpenModal,
      handleOpenStornoModal,
      handleFinalizeInvoicesSuccess,
      invalidateData,
    ],
  );

  useEffect(() => {
    setSelectedRowKeys([]);
  }, [groupingMode, setSelectedRowKeys]);

  // Single EditableTable render path for both the flat and grouped views —
  // they share every config except initialData (+ a few per-view overrides
  // passed through ``extra``; ``key`` is pulled out since React treats it
  // specially and it can't ride along in a prop spread).
  const renderInvoiceTable = (
    items: InvoiceOverviewRow[],
    {
      key,
      ...extra
    }: { key?: string } & Partial<Parameters<typeof EditableTable>[0]> = {},
  ) => (
    <EditableTable
      key={key}
      columns={normalColumns}
      initialData={items}
      loading={loading}
      permissions={READ_ONLY_PERMISSION}
      // Paginate only the flat table view; when grouped by week/month each
      // group's table shows all its rows (per-group pagination reads oddly).
      pagination={groupingMode === GROUPING_MODES.NONE}
      rowSelection={rowSelectionConfig}
      onSelectedRowsChange={handleRowSelectionChange}
      selectedRowKeys={selectedRowKeys}
      showSearchBar
      {...extra}
    />
  );

  const renderGroupedView = () => (
    <div>
      {Object.entries(groupedData).map(([groupKey, group]) => (
        <Card
          key={groupKey}
          className="invoice-group-card"
          style={{ marginBottom: 16 }}
          classNames={{ header: "invoice-group-card-header" }}
          title={
            <div className="flex-center-y" style={{ gap: "4em" }}>
              <span>{group.name}</span>
              <Flex align="center" gap={16}>
                <Text>{t("commissioning.sum")}</Text>
                <Text strong className="text-success">
                  {format(group.totalAmount, 2)} {currencySymbol}
                </Text>
              </Flex>
            </div>
          }
        >
          {renderInvoiceTable(group.items, {
            className: "w-max custom-jasmin-table invoice-group-table",
          })}
        </Card>
      ))}
    </div>
  );

  const renderTableView = () =>
    renderInvoiceTable(filteredData, {
      key: `${selectedYear}-${selectedReseller}`,
      onSaveSuccess,
      onDeleteSuccess,
    });

  return (
    <div>
      <h1>{t("commissioning.orders_without_invoices")}</h1>
      <YearSelector
        selectedYear={selectedYear}
        setSelectedYear={setSelectedYear}
      />

      <div style={{ marginBottom: "1em", marginTop: "1em" }}>
        <ResellerSelector
          selectedReseller={selectedReseller}
          setSelectedReseller={setSelectedReseller}
          has_orders_without_invoice={true}
        />
      </div>

      <div className="flex-between">
        <div>
          <Radio.Group
            value={groupingMode}
            onChange={(e) => setGroupingMode(e.target.value)}
          >
            <Radio.Button
              value={GROUPING_MODES.NONE}
              className={
                groupingMode === GROUPING_MODES.NONE
                  ? "invoice-grouping-active"
                  : undefined
              }
            >
              <TableOutlined /> {t("commissioning.table_view")}
            </Radio.Button>
            <Radio.Button
              value={GROUPING_MODES.WEEK}
              className={
                groupingMode === GROUPING_MODES.WEEK
                  ? "invoice-grouping-active"
                  : undefined
              }
            >
              <CalendarOutlined /> {t("commissioning.group_by_week")}
            </Radio.Button>
            <Radio.Button
              value={GROUPING_MODES.MONTH}
              className={
                groupingMode === GROUPING_MODES.MONTH
                  ? "invoice-grouping-active"
                  : undefined
              }
            >
              <CalendarOutlined /> {t("commissioning.group_by_month")}
            </Radio.Button>
          </Radio.Group>
          <ToolTipIcon title={t("tooltip.grouping_mode_date")} />
        </div>
      </div>
      <div style={{ marginTop: "2em", marginBottom: "-2em" }}>
        <strong>{t("commissioning.for_selected")}</strong>
      </div>
      <div className="button-row">
        {" "}
        <BulkActionButton
          selectedIds={selectedRowKeys}
          apiFunction={(payload) =>
            commissioningBulkCreateSummaryInvoiceFromOrdersCreate({
              ids: payload.ids as string[],
            })
          }
          buttonText={t("commissioning.create_summary_invoice_for_selected")}
          buttonProps={{ type: "primary" }}
          disabled={
            selectedRowKeys.length < 2 ||
            data.some(
              (item) =>
                selectedRowKeys.includes(item.id) && item.has_finalized_invoice,
            )
          }
          onSuccess={invalidateData}
        />
        <ToolTipIcon title={t("tooltip.create_summary_invoice_for_selected")} />
        <BulkActionButton
          selectedIds={selectedRowKeys}
          apiFunction={(payload) =>
            commissioningBulkCreateDocumentsFromOrdersCreate({
              ids: payload.ids as string[],
              model: "invoice" as const,
            })
          }
          buttonText={t("commissioning.create_invoice_for_selected")}
          buttonProps={{ type: "primary" }}
          disabled={
            selectedRowKeys.length === 0 ||
            data.some(
              (item) =>
                selectedRowKeys.includes(item.id) && item.has_finalized_invoice,
            )
          }
          onSuccess={invalidateData}
        />
        <ToolTipIcon title={t("tooltip.create_invoice_for_selected")} />
      </div>
      <div
        style={{
          display: "flex",
          gap: "8px",
          flexWrap: "wrap",
          marginTop: "-20px",
        }}
      >
        <BulkActionButton
          selectedIds={selectedRowKeys}
          apiFunction={(payload) =>
            commissioningBulkDeleteDocumentsCreate({
              ids: payload.ids as string[],
              model: "invoice" as const,
            })
          }
          buttonText={t("commissioning.delete_invoices")}
          buttonProps={{ type: "primary" }}
          onSuccess={invalidateData}
          disabled={
            selectedRowKeys.length === 0 ||
            data.some(
              (item) =>
                selectedRowKeys.includes(item.id) && item.has_finalized_invoice,
            ) ||
            data.some(
              (item) =>
                selectedRowKeys.includes(item.id) && item.has_invoice === false,
            )
          }
        />
        <ToolTipIcon title={t("tooltip.delete_invoices")} />

        <BulkActionButton
          selectedIds={selectedRowKeys}
          apiFunction={(payload) =>
            commissioningBulkFinalizeDocumentsCreate({
              ids: payload.ids as string[],
              model: "invoice" as const,
            })
          }
          buttonText={t("commissioning.finalize_invoices")}
          buttonProps={{ type: "primary", danger: true }}
          disabled={
            selectedRowKeys.length === 0 ||
            data.some(
              (item) =>
                selectedRowKeys.includes(item.id) &&
                item.has_finalized_invoice === true,
            )
          }
          onSuccess={handleFinalizeInvoicesSuccess}
        />
        <ToolTipIcon title={t("tooltip.finalize_invoices")} />
      </div>
      <div style={{ marginTop: "2em", marginBottom: "-2em" }}>
        <strong>{t("resellers.for_selected_finalized")}</strong>
      </div>
      <div
        style={{
          display: "flex",
          gap: "8px",
          flexWrap: "wrap",
          marginBottom: "16px",
          marginTop: "-20px",
        }}
      >
        {/* Bulk send-email is still a disabled placeholder: its backend route
              doesn't exist yet (a click used to 404). Re-enable with the real
              endpoint once it lands. */}
        <BulkActionButton
          selectedIds={selectedRowKeys}
          buttonText={t("resellers.send_via_email_resellers")}
          buttonProps={{ type: "primary" }}
          disabled
        />
        {/* Download the selected invoices' finalized e-PDFs (ZUGFeRD) as a
              single ZIP, built client-side. Enabled whenever at least one
              selected row carries a finalized invoice; non-finalized rows are
              skipped and an empty result surfaces a subtle notice. */}
        <BulkActionButton
          selectedIds={selectedRowKeys}
          apiFunction={handleDownloadBulkZip}
          buttonText={t("download.selected_invoices_bulk_zip")}
          buttonProps={{ type: "primary" }}
          errorMessage={t("download.bulk_zip_failed")}
          disabled={selectedFinalizedInvoiceIds.length === 0}
        />
      </div>

      {groupingMode === GROUPING_MODES.NONE
        ? renderTableView()
        : renderGroupedView()}

      <ExplainerText title={t("common.info")}>
        {t("explainers.invoices")}
      </ExplainerText>

      {modalVisible && selectedInvoiceId && (
        <InvoiceModal
          visible={modalVisible}
          onClose={handleCloseModal}
          invoiceId={selectedInvoiceId}
        />
      )}

      <StornoInvoiceModal
        open={stornoModalVisible}
        invoiceLabel={stornoTargetLabel}
        loading={createStornoMutation.isPending}
        onCancel={() => {
          setStornoModalVisible(false);
          setStornoTargetInvoiceId(null);
        }}
        onConfirm={handleCreateStorno}
      />
    </div>
  );
}
