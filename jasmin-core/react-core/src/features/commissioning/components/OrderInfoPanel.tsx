import { CheckOutlined, EditOutlined } from "@ant-design/icons";
import { Input } from "antd";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { BulkActionButton, ToolTipIcon, ViewDetailsButton } from "@shared/ui";
import {
  commissioningBulkCreateDocumentsFromOrdersCreate,
  commissioningBulkDeleteDocumentsCreate,
  commissioningBulkFinalizeDocumentsCreate,
} from "@shared/api/generated/commissioning/commissioning";
import type { OrderState } from "@features/commissioning/hooks/useOrdersData";
import { DeliveryNotePDFButtons, InvoicePDFButtons } from "@features/commissioning/pdfs";

interface OrderInfoPanelProps {
  orderState: OrderState;
  formattedOrderNumber: string;
  totalSum: string;
  fetchData: () => void;
  handleFinalizeDNSuccess: (data: unknown) => void;
  handleFinalizeInvoicesSuccess: (data: unknown) => void;
  handleCreateInvoiceSuccess: (data: unknown) => void;
  onOpenDeliveryNoteModal: () => void;
  onOpenInvoiceModal: () => void;
  orderNote: string;
  onOrderNoteChange: (note: string) => void;
}

export function OrderInfoPanel({
  orderState,
  formattedOrderNumber,
  totalSum,
  fetchData,
  handleFinalizeDNSuccess,
  handleFinalizeInvoicesSuccess,
  handleCreateInvoiceSuccess,
  onOpenDeliveryNoteModal,
  onOpenInvoiceModal,
  orderNote,
  onOrderNoteChange,
}: OrderInfoPanelProps) {
  const { t } = useTranslation();

  const {
    orderId,
    orderNumber,
    isOrderFinalized,
    deliveryNoteId,
    deliveryNoteNumber,
    deliveryNotePrefix,
    isDeliveryNoteFinalized,
    invoiceId,
    invoiceNumber,
    invoicePrefix,
    hasFinalizedInvoice,
  } = orderState;

  const [isEditingNote, setIsEditingNote] = useState(false);
  const noteRef = useRef<ReturnType<typeof Input.TextArea> | null>(null);

  return (
    <div className="order-info">
      <div className="order-row">
        <span className="order-label">
          {t("resellers.order_number")}:
          <ToolTipIcon title={t("tooltip.order_number")} />
        </span>
        <span className="order-value">
          {isOrderFinalized ? (
            <>
              <CheckOutlined aria-hidden className="icon-check-success" />
              <span className="sr-only">{t("commissioning.finalized")}</span>
            </>
          ) : (
            <span className="sr-only">{t("commissioning.not_finalized")}</span>
          )}
          {formattedOrderNumber}
        </span>
      </div>

      <div className="order-row">
        <span className="order-label">{t("resellers.total_sum_brutto")}:</span>
        <span className="order-value">
          {isOrderFinalized ? (
            <>
              <CheckOutlined aria-hidden className="icon-check-success" />
              <span className="sr-only">{t("commissioning.finalized")}</span>
            </>
          ) : (
            <span className="sr-only">{t("commissioning.not_finalized")}</span>
          )}
          {totalSum}
        </span>
      </div>

      {orderId && (
        <div className="order-row">
          <span className="order-label">
            {t("commissioning.note")}:
            <ToolTipIcon title={t("tooltip.order_note")} />
          </span>
          {isEditingNote ? (
            <Input.TextArea
              ref={noteRef as never}
              value={orderNote}
              onChange={(e) => onOrderNoteChange(e.target.value)}
              placeholder={t("commissioning.note")}
              autoSize={{ minRows: 1, maxRows: 3 }}
              style={{ maxWidth: "30em" }}
              maxLength={500}
              autoFocus
              onPressEnter={(e) => {
                e.preventDefault();
                setIsEditingNote(false);
              }}
              onBlur={() => setIsEditingNote(false)}
            />
          ) : (
            <span
              className="order-value"
              style={{
                cursor: "pointer",
                minWidth: "10em",
                display: "inline-flex",
                alignItems: "center",
                gap: "0.5em",
              }}
              role="button"
              tabIndex={0}
              onClick={() => setIsEditingNote(true)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setIsEditingNote(true);
                }
              }}
            >
              {orderNote || <span style={{ color: "var(--color-text-tertiary)" }}>—</span>}
              <EditOutlined
                style={{
                  fontSize: "0.85em",
                  color: "var(--color-text-tertiary)",
                }}
              />
            </span>
          )}
        </div>
      )}

      <div className="order-row">
        <span className="order-label">
          {t("resellers.delivery_note_number")}:
          <ToolTipIcon title={t("tooltip.delivery_note_number")} />
        </span>
        <span className="order-value">
          {isDeliveryNoteFinalized ? (
            <>
              <CheckOutlined aria-hidden className="icon-check-success" />
              <span className="sr-only">{t("commissioning.finalized")}</span>
            </>
          ) : (
            <span className="sr-only">{t("commissioning.not_finalized")}</span>
          )}
          {deliveryNotePrefix || ""}-{deliveryNoteNumber || "---"}
        </span>

        <div className="button-row">
          {deliveryNoteNumber && (
            <ViewDetailsButton
              onClick={onOpenDeliveryNoteModal}
              label={t("commissioning.view_details_delivery_note")}
            />
          )}
          {isDeliveryNoteFinalized && (
            <DeliveryNotePDFButtons
              deliveryNoteId={deliveryNoteId}
              buttonText={t("commissioning.pdf")}
              buttonSize="small"
            />
          )}
          {!deliveryNoteNumber && (
            <BulkActionButton
              selectedIds={orderId ? [orderId] : []}
              apiFunction={(payload) =>
                commissioningBulkCreateDocumentsFromOrdersCreate(
                  payload as never,
                )
              }
              buttonText={t("commissioning.create_delivery_note")}
              buttonProps={{ type: "primary" }}
              disabled={!orderNumber}
              onSuccess={fetchData}
              payload={{ model: "delivery_note" }}
              style={{ marginTop: "0em" }}
            />
          )}
          {!isDeliveryNoteFinalized && deliveryNoteNumber && (
            <BulkActionButton
              selectedIds={orderId ? [orderId] : []}
              apiFunction={(payload) =>
                commissioningBulkFinalizeDocumentsCreate(payload as never)
              }
              buttonText={t("commissioning.finalize_delivery_note")}
              buttonProps={{ type: "primary" }}
              onSuccess={handleFinalizeDNSuccess}
              payload={{ model: "delivery_note" }}
              style={{ marginTop: "0em" }}
            />
          )}
          {!isDeliveryNoteFinalized && deliveryNoteNumber && (
            <BulkActionButton
              selectedIds={orderId ? [orderId] : []}
              apiFunction={(payload) =>
                commissioningBulkDeleteDocumentsCreate(payload as never)
              }
              buttonText={t("commissioning.delete_delivery_note")}
              buttonProps={{ type: "primary", danger: true }}
              onSuccess={fetchData}
              payload={{ model: "delivery_note" }}
              style={{ marginTop: "0em" }}
            />
          )}
        </div>
        <ToolTipIcon title={t("tooltip.delivery_note_creation")} />
      </div>

      <div className="order-row">
        <span className="order-label">
          {t("resellers.invoice_number")}:
          <ToolTipIcon title={t("tooltip.invoice_number")} />
        </span>
        <span className="order-value">
          {hasFinalizedInvoice ? (
            <>
              <CheckOutlined aria-hidden className="icon-check-success" />
              <span className="sr-only">{t("commissioning.finalized")}</span>
            </>
          ) : (
            <span className="sr-only">{t("commissioning.not_finalized")}</span>
          )}
          {invoicePrefix || ""}-{invoiceNumber || "---"}
        </span>

        <div className="button-row">
          {invoiceNumber && (
            <ViewDetailsButton
              onClick={onOpenInvoiceModal}
              label={t("commissioning.view_details_invoice")}
            />
          )}
          {hasFinalizedInvoice && (
            <InvoicePDFButtons
              invoiceId={invoiceId}
              buttonText={t("commissioning.pdf")}
              buttonSize="small"
            />
          )}
          {!invoiceNumber && (
            <BulkActionButton
              selectedIds={orderId ? [orderId] : []}
              apiFunction={(payload) =>
                commissioningBulkCreateDocumentsFromOrdersCreate(
                  payload as never,
                )
              }
              buttonText={t("commissioning.create_invoice")}
              buttonProps={{ type: "primary" }}
              onSuccess={handleCreateInvoiceSuccess}
              disabled={!deliveryNoteNumber}
              payload={{ model: "invoice" }}
              style={{ marginTop: "0em" }}
            />
          )}
          {!hasFinalizedInvoice && invoiceNumber && (
            <BulkActionButton
              selectedIds={orderId ? [orderId] : []}
              apiFunction={(payload) =>
                commissioningBulkFinalizeDocumentsCreate(payload as never)
              }
              buttonText={t("commissioning.finalize_invoice")}
              buttonProps={{ type: "primary" }}
              onSuccess={handleFinalizeInvoicesSuccess}
              payload={{ model: "invoice" }}
              style={{ marginTop: "0em" }}
            />
          )}
          {!hasFinalizedInvoice && invoiceNumber && (
            <BulkActionButton
              selectedIds={orderId ? [orderId] : []}
              apiFunction={(payload) =>
                commissioningBulkDeleteDocumentsCreate(payload as never)
              }
              buttonText={t("commissioning.delete_invoice")}
              buttonProps={{ type: "primary", danger: true }}
              onSuccess={fetchData}
              payload={{ model: "invoice" }}
              style={{ marginTop: "0em" }}
            />
          )}
        </div>
        <ToolTipIcon title={t("tooltip.invoice_creation")} />
      </div>
    </div>
  );
}
