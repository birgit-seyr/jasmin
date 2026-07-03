import { CheckOutlined, SendOutlined } from "@ant-design/icons";
import { Button, message } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningBulkCreateDocumentsFromOrdersCreate,
  commissioningBulkDeleteDocumentsCreate,
  commissioningBulkFinalizeDocumentsCreate,
  commissioningDeliveryNoteContentsCreate,
  commissioningDeliveryNoteContentsPartialUpdate,
  commissioningDeliveryNotesDestroy,
  commissioningDeliveryNotesSendToResellerCreate,
  useCommissioningOrdersOverviewList,
} from "@shared/api/generated/commissioning/commissioning";
import { getErrorMessage } from "@shared/utils/apiError";
import type {
  BulkDocumentRequest,
  BulkOperationResponse,
  CombinedOrderOverview,
  CommissioningOrdersOverviewListParams,
  DeliveryNoteResellerContent,
} from "@shared/api/generated/models";
import { DeliveryNoteModal } from "@features/commissioning/modals";
import { DeliveryNotePDFButtons } from "@features/commissioning/pdfs";
// Helper imported directly from its dedicated file — the file has
// no top-level @react-pdf static import, so this page's eager
// bundle does NOT carry the ~484 KB gzip PDF chunk. See
// generateDeliveryNotePDF.tsx's docstring for the architecture.
import { generateAndUploadDeliveryNotePDF } from "@features/commissioning/pdfs/forResellers/generateDeliveryNotePDF";
import { ResellerSelector, WeekSelector } from "@shared/selectors";
import {
  EditableTable,
  READ_ONLY_PERMISSION,
  wrapApiFunctions,
} from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { BulkActionButton, ExplainerText, ViewDetailsButton } from "@shared/ui";
import { useDateFormat, useTableRowSelection, useTenant } from "@hooks/index";

const currentYear = dayjs().year();
const currentWeek = dayjs().isoWeek();

/** A table row: the generated overview shape + the EditableTable key. */
type DeliveryNoteOverviewRow = CombinedOrderOverview & TableRecord;

export default function DeliveryNotes() {
  const [selectedYear, setSelectedYear] = useState(currentYear);
  const [selectedWeek, setSelectedWeek] = useState<number | null>(currentWeek);
  const [selectedReseller, setSelectedReseller] = useState<string | null>(null);
  const { getSetting, tenant, logoUrl, bioLogoUrl } = useTenant();

  // Modal state
  const [modalVisible, setModalVisible] = useState(false);
  const [selectedDeliveryNoteId, setSelectedDeliveryNoteId] = useState<
    string | null
  >(null);

  const { formatDate } = useDateFormat() as {
    formatDate: (value: string | null | undefined) => string;
  };

  const { t } = useTranslation();

  const listParams = useMemo<CommissioningOrdersOverviewListParams>(
    () => ({
      year: selectedYear,
      ...(selectedWeek != null ? { delivery_week: selectedWeek } : {}),
      ...(selectedReseller ? { reseller: selectedReseller } : {}),
    }),
    [selectedYear, selectedWeek, selectedReseller],
  );

  // Fetch main data
  const {
    data: ordersData,
    isFetching,
    refetch: refetchOrders,
  } = useCommissioningOrdersOverviewList(listParams);

  const data = useMemo<DeliveryNoteOverviewRow[]>(
    () => (ordersData ?? []).map((item) => ({ ...item, key: item.id })),
    [ordersData],
  );

  // Track which DN ID is currently being sent so we can disable
  // its button and show a spinner.
  const [sendingDeliveryNoteId, setSendingDeliveryNoteId] = useState<
    string | null
  >(null);

  const handleSendDeliveryNoteToReseller = useCallback(
    async (deliveryNoteId: string | null | undefined) => {
      if (!deliveryNoteId) return;
      setSendingDeliveryNoteId(deliveryNoteId);
      try {
        const data =
          await commissioningDeliveryNotesSendToResellerCreate(deliveryNoteId);
        if (data.sent) {
          message.success(t("commissioning.delivery_note_sent_to_reseller"));
          await refetchOrders();
        } else {
          message.warning(t("commissioning.delivery_note_send_failed"));
        }
      } catch (err) {
        message.error(getErrorMessage(err, t("common.error_loading_data")));
      } finally {
        setSendingDeliveryNoteId(null);
      }
    },
    [t, refetchOrders],
  );

  // row selection state and handler:
  const {
    selectedRowKeys,
    onSelectedRowsChange: handleRowSelectionChange,
    rowSelection: rowSelectionConfig,
  } = useTableRowSelection();

  const handleFinalizeDNSuccess = useCallback(
    async (responseData: BulkOperationResponse) => {
      const dnIds = (responseData?.results ?? [])
        .filter((r) => r.success && r.delivery_note_id)
        .map((r) => r.delivery_note_id);

      for (const id of dnIds) {
        try {
          await generateAndUploadDeliveryNotePDF(
            id,
            t,
            tenant as Record<string, unknown>,
            getSetting,
            logoUrl,
            bioLogoUrl,
          );
        } catch (err) {
          console.error(`PDF generation failed for delivery note ${id}:`, err);
        }
      }

      refetchOrders();
    },
    [t, tenant, getSetting, logoUrl, bioLogoUrl, refetchOrders],
  );

  const bulkCreateDocuments = useCallback(
    (payload: Record<string, unknown>) =>
      commissioningBulkCreateDocumentsFromOrdersCreate(
        payload as unknown as BulkDocumentRequest,
      ),
    [],
  );

  const bulkFinalizeDocuments = useCallback(
    (payload: Record<string, unknown>) =>
      commissioningBulkFinalizeDocumentsCreate(
        payload as unknown as BulkDocumentRequest,
      ),
    [],
  );

  const handleOpenModal = useCallback((record: CombinedOrderOverview) => {
    setSelectedDeliveryNoteId(record.delivery_note_id);
    setModalVisible(true);
  }, []);

  const handleCloseModal = useCallback(() => {
    setModalVisible(false);
    setSelectedDeliveryNoteId(null);
    refetchOrders();
  }, [refetchOrders]);

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<DeliveryNoteResellerContent & TableRecord>({
        create: (payload) => commissioningDeliveryNoteContentsCreate(payload),
        update: (id, payload) =>
          commissioningDeliveryNoteContentsPartialUpdate(id, payload),
        delete: (id) => commissioningDeliveryNotesDestroy(id),
      }),
    [],
  );

  const columns = useMemo<EditableColumnConfig<TableRecord>[]>(
    () => [
      {
        title: <>{t("resellers.order_date")}</>,
        dataIndex: "order_date",
        key: "order_date",
        readOnly: true,
        inputType: "date",

        width: "10em",
        align: "center",
        disabled: true,
        sortable: true,

        render: (value: unknown) => formatDate(value as string),
      },
      {
        title: <>{t("resellers.order_number")}</>,
        dataIndex: "order_number",
        key: "order_number",
        width: "12em",
        inputType: "text",
        readOnly: true,
        align: "left",
        disabled: true,
        sortable: true,
        render: (value: unknown, record) => {
          const r = record as unknown as CombinedOrderOverview;
          return (
            <>
              {r.order_is_finalized ? (
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
          );
        },
      },
      {
        title: <>{t("resellers.reseller_name")}</>,
        dataIndex: "reseller_name",
        key: "reseller_name",
        inputType: "text",
        readOnly: true,
        width: "15em",
        align: "left",
        disabled: true,
        sortable: true,
      },

      {
        title: <>{t("resellers.delivery_note_date")}</>,
        dataIndex: "delivery_note_date",
        key: "delivery_note_date",
        readOnly: true,
        inputType: "date",
        width: "9em",
        align: "center",
        disabled: true,
        sortable: true,

        render: (value: unknown) => formatDate(value as string),
      },
      {
        title: <>{t("resellers.delivery_note_number")}</>,
        dataIndex: "delivery_note_number",
        key: "delivery_note_number",
        readOnly: true,
        width: "12em",
        align: "left",
        inputType: "text",
        disabled: true,
        sortable: true,
        render: (value: unknown, record) => {
          const r = record as unknown as CombinedOrderOverview;
          return (
            <>
              {r.delivery_note_is_finalized ? (
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
          );
        },
      },
      {
        title: "",
        dataIndex: "actions",
        key: "actions",
        readOnly: true,
        disabled: true,
        render: (_: unknown, rec) => {
          const record = rec as unknown as CombinedOrderOverview;
          return (
            <div className="button-row">
              <>
                {record.has_delivery_note && (
                  <ViewDetailsButton
                    onClick={() => handleOpenModal(record)}
                    label={t("commissioning.view_details_invoice")}
                  />
                )}
                {record.delivery_note_is_finalized && (
                  <DeliveryNotePDFButtons
                    deliveryNoteId={record.delivery_note_id}
                    buttonText={t("commissioning.pdf")}
                    buttonSize="small"
                  />
                )}
                {record.delivery_note_is_finalized &&
                  !record.delivery_note_has_been_sent_to_reseller && (
                    // P0-3: manual "Send to reseller" button. Only
                    // shows on finalized DNs that haven't been sent
                    // yet — re-send is intentionally NOT a one-click
                    // action (delivery notes are paper-canonical, the
                    // email is an opt-in advance-notice). Backend
                    // rejects with 400 if the reseller has no
                    // invoice_email configured.
                    <Button
                      type="primary"
                      size="small"
                      icon={<SendOutlined />}
                      loading={
                        sendingDeliveryNoteId === record.delivery_note_id
                      }
                      disabled={
                        sendingDeliveryNoteId !== null &&
                        sendingDeliveryNoteId !== record.delivery_note_id
                      }
                      onClick={() =>
                        handleSendDeliveryNoteToReseller(
                          record.delivery_note_id,
                        )
                      }
                    >
                      {t("commissioning.send_delivery_note_to_reseller")}
                    </Button>
                  )}
                {!record.has_delivery_note && (
                  <BulkActionButton
                    selectedIds={record.id ? [record.id] : []}
                    apiFunction={bulkCreateDocuments}
                    buttonText={t("commissioning.create_delivery_note")}
                    buttonProps={{ type: "primary" }}
                    disabled={!record.order_number || data.length === 0}
                    onSuccess={() => refetchOrders()}
                    payload={{ model: "delivery_note" }}
                    style={{ marginTop: "0em" }}
                  />
                )}
                {!record.delivery_note_is_finalized &&
                  record.has_delivery_note && (
                    <BulkActionButton
                      selectedIds={record.id ? [record.id] : []}
                      apiFunction={bulkFinalizeDocuments}
                      buttonText={t("commissioning.finalize_delivery_note")}
                      buttonProps={{ type: "primary" }}
                      onSuccess={handleFinalizeDNSuccess}
                      payload={{ model: "delivery_note" }}
                      style={{ marginTop: "0em" }}
                    />
                  )}
                {!record.delivery_note_is_finalized &&
                  record.has_delivery_note && (
                    <BulkActionButton
                      selectedIds={record.id ? [record.id] : []}
                      apiFunction={(payload) =>
                        commissioningBulkDeleteDocumentsCreate(payload as never)
                      }
                      buttonText={t("commissioning.delete_delivery_note")}
                      buttonProps={{ type: "primary", danger: true }}
                      onSuccess={() => refetchOrders()}
                      payload={{ model: "delivery_note" }}
                      style={{ marginTop: "0em" }}
                    />
                  )}
              </>
            </div>
          );
        },
      },
      {
        title: <>{t("resellers.sent_via_email")}</>,
        dataIndex: "delivery_note_has_been_sent_to_reseller",
        key: "delivery_note_has_been_sent_to_reseller",
        inputType: "checkbox",
        required: false,
        align: "left",
        disabled: true,
        sortable: true,
      },
      ...(selectedReseller === "none"
        ? ([
            {
              title: <>{t("resellers.resellers")}</>,
              dataIndex: "reseller_name",
              key: "reseller_name",
              inputType: "text",
              required: false,
              align: "left",
              disabled: true,
              sortable: true,
            },
          ] as EditableColumnConfig<TableRecord>[])
        : []),
    ],
    [
      bulkCreateDocuments,
      bulkFinalizeDocuments,
      data.length,
      formatDate,
      handleFinalizeDNSuccess,
      handleOpenModal,
      handleSendDeliveryNoteToReseller,
      refetchOrders,
      selectedReseller,
      sendingDeliveryNoteId,
      t,
    ],
  );

  return (
    <div>
      <h1>{t("commissioning.delivery_notes")}</h1>
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
          delivery_day={null}
          include_null_option={true}
        />
      </div>
      <div className="bulk-actions-header">
        <strong>{t("commissioning.for_selected")}</strong>
      </div>
      <div className="button-row">
        <BulkActionButton
          selectedIds={selectedRowKeys}
          apiFunction={bulkCreateDocuments}
          buttonText={t("commissioning.create_delivery_notes_bulk")}
          buttonProps={{ type: "primary" }}
          disabled={
            selectedRowKeys.length === 0 ||
            data.some(
              (item) =>
                selectedRowKeys.includes(item.id) &&
                item.delivery_note_is_finalized,
            )
          }
          onSuccess={() => refetchOrders()}
          payload={{ model: "delivery_note" }}
        />
        <BulkActionButton
          selectedIds={selectedRowKeys}
          apiFunction={bulkFinalizeDocuments}
          buttonText={t("commissioning.finalize_delivery_notes")}
          buttonProps={{ type: "primary", danger: true }}
          disabled={
            selectedRowKeys.length === 0 ||
            data.some(
              (item) =>
                selectedRowKeys.includes(item.id) &&
                item.delivery_note_is_finalized,
            )
          }
          onSuccess={handleFinalizeDNSuccess}
          payload={{ model: "delivery_note" }}
        />
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
        {/* Bulk send-email / download-PDF / download-ZIP are disabled
            placeholders: the backend routes don't exist yet (a click used to
            404). Re-enable with the real apiFunction + per-row disabled logic
            once the endpoints land. */}
        <BulkActionButton
          selectedIds={selectedRowKeys}
          buttonText={t("commissioning.send_delivery_notes_bulk_via_email")}
          buttonProps={{ type: "primary" }}
          disabled
        />
        <BulkActionButton
          selectedIds={selectedRowKeys}
          buttonText={t("download.selected_delivery_notes_bulk_pdf")}
          buttonProps={{ type: "primary" }}
          disabled
        />
        <BulkActionButton
          selectedIds={selectedRowKeys}
          buttonText={t("download.selected_delivery_notes_bulk_zip")}
          buttonProps={{ type: "primary" }}
          disabled
        />
      </div>
      <EditableTable
        key={`${selectedYear}-${selectedWeek}-${selectedReseller}`}
        columns={columns}
        apiFunctions={apiFunctions}
        focusIndex="share_article_name"
        initialData={data}
        loading={isFetching}
        permissions={READ_ONLY_PERMISSION}
        rowSelection={rowSelectionConfig}
        onSelectedRowsChange={handleRowSelectionChange}
        selectedRowKeys={selectedRowKeys}
        showSearchBar
        pagination={true}
      />

      <ExplainerText title={t("common.info")}>
        {t("explainers.create_multiple_delivery_notes")}
      </ExplainerText>
      <DeliveryNoteModal
        visible={modalVisible}
        onClose={handleCloseModal}
        deliveryNoteId={selectedDeliveryNoteId}
      />
    </div>
  );
}
