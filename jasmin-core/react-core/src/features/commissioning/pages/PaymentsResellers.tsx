import { CheckOutlined } from "@ant-design/icons";
import { Tag } from "antd";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { isWeekInPast } from "@shared/utils";
import { useTranslation } from "react-i18next";
import {
  commissioningBulkSendInvoiceRemindersViaEmailCreate,
  commissioningBulkSetToPaidDocumentsCreate,
  commissioningSetInvoiceNotePartialUpdate,
  getCommissioningOrdersOverviewListQueryKey,
  useCommissioningOrdersOverviewList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  BulkDocumentRequest,
  CombinedOrderOverview,
  CommissioningOrdersOverviewListParams,
  SetInvoiceNoteRequest,
} from "@shared/api/generated/models";
import { JobProgressDrawer } from "@shared/ui/JobProgressDrawer";
import { ResellerSelector, WeekSelector } from "@shared/selectors";
import {
  EditableTable,
  gatedByPermissionOnlyEdit,
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
  LabeledSwitch,
  ToolTipIcon,
} from "@shared/ui";
import {
  useCurrency,
  useDateFormat,
  useInvalidateAfterTableMutation,
  useNoteColumn,
  useTableRowSelection,
  useYearWeekState,
} from "@hooks/index";

type CombinedOrderOverviewRow = CombinedOrderOverview & TableRecord;

export default function PaymentsResellers() {
  const { selectedYear, setSelectedYear, selectedWeek, setSelectedWeek } =
    useYearWeekState();
  const [selectedReseller, setSelectedReseller] = useState<string | null>(null);
  const isPast = useMemo(
    () => isWeekInPast(selectedYear, selectedWeek),
    [selectedYear, selectedWeek],
  );
  const [showOnlyNotPaid, setShowOnlyNotPaid] = useState(false);
  // Active Huey-backed reminder-send job, polled by the
  // JobProgressDrawer below. ``null`` when no send is in flight.
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { formatDate } = useDateFormat();
  const { noteColumn } = useNoteColumn();

  const { t } = useTranslation();

  const { formatCurrency } = useCurrency();

  const listParams = useMemo<CommissioningOrdersOverviewListParams>(
    () => ({
      year: selectedYear,
      delivery_week: selectedWeek ?? undefined,
      reseller: selectedReseller ?? undefined,
    }),
    [selectedYear, selectedWeek, selectedReseller],
  );

  const { data: rawData, isFetching } =
    useCommissioningOrdersOverviewList(listParams);
  const data = useMemo(
    () => (rawData ?? []) as unknown as CombinedOrderOverviewRow[],
    [rawData],
  );

  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningOrdersOverviewListQueryKey(listParams),
    });
  }, [queryClient, listParams]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

  const {
    selectedRowKeys,
    onSelectedRowsChange: handleRowSelectionChange,
    rowSelection: rowSelectionConfig,
  } = useTableRowSelection();

  const columns = useMemo<EditableColumnConfig<CombinedOrderOverviewRow>[]>(
    () =>
      [
        {
          title: <>{t("commissioning.invoice_date_short")}</>,
          dataIndex: "invoice_date",
          key: "invoice_date",
          inputType: "date",
          required: true,
          width: "10em",
          align: "left",
          disabled: true,
          sortable: true,
          render: (value: unknown) => formatDate(value as string),
        },
        {
          title: t("commissioning.invoice_number"),
          dataIndex: "invoice_number",
          key: "invoice_number",
          width: "10em",
          inputType: "text",
          sortable: true,
          disabled: true,
          render: (value: unknown, record: CombinedOrderOverviewRow) => (
            <>
              {record.has_finalized_invoice ? (
                <>
                  <CheckOutlined aria-hidden className="icon-check-success" />
                  <span className="sr-only">
                    {t("commissioning.finalized")}
                  </span>
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
          title: t("commissioning.invoice_total_amount_netto"),
          dataIndex: "sum_netto",
          key: "sum_netto",
          width: "12em",
          align: "right",
          disabled: true,
          inputType: "decimal2",
          sortable: true,

          render: (value: unknown) =>
            formatCurrency(parseFloat((value as string) || "0")),
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
          readOnly: true,
          sortable: true,
        },
        {
          title: <>{t("resellers.has_been_sent_to_accounting")}</>,
          dataIndex: "invoice_has_been_sent_to_accounting",
          key: "invoice_has_been_sent_to_accounting",
          inputType: "checkbox",
          disabled: true,
          readOnly: true,
          sortable: true,
        },
        {
          title: <>{t("resellers.has_been_paid")}</>,
          dataIndex: "has_been_paid",
          key: "has_been_paid",
          inputType: "checkbox",
          disabled: true,
          sortable: true,
        },
        {
          title: "",
          dataIndex: "actions",
          key: "actions",
          readOnly: true,
          disabled: true,
          width: "15em",
          render: (_: unknown, record: CombinedOrderOverviewRow) => (
            <div className="button-row">
              <>
                {record.invoice_cancelled_by ? (
                  <Tag color="red">
                    {t("commissioning.cancelled_by")}
                    {record.invoice_storno_number
                      ? ` ${record.invoice_storno_number}`
                      : ""}
                  </Tag>
                ) : (
                  !record.has_been_paid && (
                    <BulkActionButton
                      selectedIds={record.id ? [record.id as string] : []}
                      apiFunction={(payload) =>
                        commissioningBulkSetToPaidDocumentsCreate(
                          payload as unknown as BulkDocumentRequest,
                        )
                      }
                      buttonText={t("commissioning.set_to_paid")}
                      buttonProps={{ type: "primary" }}
                      onSuccess={invalidateData}
                      payload={{ model: "invoice" }}
                      style={{ marginTop: "0em" }}
                    />
                  )
                )}
              </>
            </div>
          ),
        },
        {
          ...noteColumn,
          inputType: "optional",
          width: "25em",
        },
      ] as EditableColumnConfig<CombinedOrderOverviewRow>[],
    [t, formatCurrency, formatDate, invalidateData, noteColumn],
  );

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<SetInvoiceNoteRequest & TableRecord>({
        update: (id, updateData) =>
          commissioningSetInvoiceNotePartialUpdate(id, updateData),
      }),
    [],
  );

  const filteredData = useMemo(() => {
    let filtered = data.filter((item) => item.has_finalized_invoice);

    if (showOnlyNotPaid) {
      filtered = filtered.filter((item) => !item.has_been_paid);
    }

    return filtered;
  }, [data, showOnlyNotPaid]);

  // Reseller payments are edit-only (add/delete disabled).
  const permissions = useMemo(() => gatedByPermissionOnlyEdit(true), []);

  return (
    <div>
      <h1>{t("commissioning.payments")}</h1>
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          marginBottom: "1em",
        }}
      >
        <WeekSelector
          selectedYear={selectedYear}
          setSelectedYear={setSelectedYear}
          selectedWeek={selectedWeek}
          setSelectedWeek={setSelectedWeek}
          include_null_option={true}
        />
      </div>
      <div style={{ marginBottom: "1em" }}>
        <ResellerSelector
          selectedReseller={selectedReseller}
          setSelectedReseller={setSelectedReseller}
          year={selectedYear}
          delivery_week={selectedWeek}
          include_null_option={true}
        />
      </div>
      <div className="section-divider">
        <LabeledSwitch
          value={showOnlyNotPaid}
          onChange={setShowOnlyNotPaid}
          label={t("commissioning.show_only_not_paid")}
          withEyeIcons
        />
      </div>
      {!isPast && (
        <div className="bulk-actions-header">
          <strong>{t("commissioning.for_selected")}</strong>
        </div>
      )}
      {!isPast && (
        <div className="button-row">
          <BulkActionButton
            selectedIds={selectedRowKeys}
            apiFunction={(payload) =>
              commissioningBulkSetToPaidDocumentsCreate(
                payload as unknown as BulkDocumentRequest,
              )
            }
            buttonText={t("commissioning.set_to_paid_bulk")}
            buttonProps={{ type: "primary" }}
            disabled={
              selectedRowKeys.length === 0 ||
              data.every(
                (item) =>
                  selectedRowKeys.includes(item.id) && item.has_been_paid,
              )
            }
            onSuccess={invalidateData}
            payload={{ model: "invoice" }}
          />
          <BulkActionButton
            selectedIds={selectedRowKeys}
            apiFunction={(payload) =>
              commissioningBulkSetToPaidDocumentsCreate(
                payload as unknown as BulkDocumentRequest,
                { undo: "true" },
              )
            }
            buttonText={t("commissioning.set_to_unpaid_bulk")}
            buttonProps={{ type: "primary" }}
            disabled={
              selectedRowKeys.length === 0 ||
              data.every(
                (item) =>
                  selectedRowKeys.includes(item.id) && !item.has_been_paid,
              )
            }
            onSuccess={invalidateData}
            payload={{ model: "invoice" }}
          />
          <BulkActionButton
            selectedIds={selectedRowKeys}
            apiFunction={(payload) =>
              commissioningBulkSendInvoiceRemindersViaEmailCreate(
                payload as unknown as BulkDocumentRequest,
              )
            }
            buttonText={t("commissioning.send_reminders_bulk_via_email")}
            buttonProps={{ type: "primary" }}
            disabled={
              selectedRowKeys.length === 0 ||
              data.some(
                (item) =>
                  selectedRowKeys.includes(item.id) && item.has_been_paid,
              )
            }
            onSuccess={(responseData) => {
              // The endpoint now returns 202 + ``{job_id, kind,
              // status}``. Open the JobProgressDrawer to poll until
              // the Huey worker finishes the per-reseller dispatch.
              const jobId = (responseData as { job_id?: string })?.job_id;
              if (jobId) setActiveJobId(jobId);
            }}
            payload={{ model: "invoice" }}
          />
        </div>
      )}

      <EditableTable
        key={`${selectedYear}-${selectedWeek}-${selectedReseller}`}
        columns={columns}
        apiFunctions={apiFunctions}
        focusIndex="share_article_name"
        initialData={filteredData}
        loading={isFetching}
        permissions={permissions}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        rowSelection={rowSelectionConfig}
        onSelectedRowsChange={handleRowSelectionChange}
        selectedRowKeys={selectedRowKeys}
        showSearchBar
        pagination={true}
      />

      <ExplainerText title={t("common.info")}>
        {t("explainers.payment_resellers")}
      </ExplainerText>

      <JobProgressDrawer
        jobId={activeJobId}
        onClose={() => {
          // Closing refreshes the payments table — the per-reseller
          // emails just went out; no field on the rows changes today,
          // but invalidating keeps the cache honest if a future
          // change stamps a ``last_reminder_sent_at``.
          invalidateData();
          setActiveJobId(null);
        }}
        title={t("commissioning.send_reminders_bulk_via_email")}
      />
    </div>
  );
}
