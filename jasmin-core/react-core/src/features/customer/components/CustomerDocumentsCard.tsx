import { DownloadOutlined, FilePdfOutlined } from "@ant-design/icons";
import { Button, Card, Col, Row, Space, Typography } from "antd";
import { useTranslation } from "react-i18next";
import {
  useCommissioningDeliveryNotesRetrieve,
  useCommissioningInvoicesRetrieve,
} from "@shared/api/generated/commissioning/commissioning";
import type { OrderContentListItem } from "@shared/api/generated/models";

const { Text } = Typography;

interface Props {
  orderContents: OrderContentListItem[];
}

export default function CustomerDocumentsCard({ orderContents }: Props) {
  const { t } = useTranslation();

  const deliveryNoteId =
    orderContents.find((i) => i.delivery_note_id)?.delivery_note_id ?? null;
  const invoiceId =
    orderContents.find((i) => i.invoice_id)?.invoice_id ?? null;
  const deliveryNoteIsFinalized = orderContents.some(
    (i) => i.delivery_note_is_finalized === true,
  );
  const invoiceIsFinalized = orderContents.some(
    (i) => i.has_finalized_invoice === true,
  );

  const { data: deliveryNote } = useCommissioningDeliveryNotesRetrieve(
    deliveryNoteId!,
    { query: { enabled: !!deliveryNoteId && deliveryNoteIsFinalized } },
  );

  const { data: invoice } = useCommissioningInvoicesRetrieve(invoiceId!, {
    query: { enabled: !!invoiceId && invoiceIsFinalized },
  });

  // If the invoice was cancelled, ``cancelled_by_invoice`` points at the
  // storno. Don't serve a cancelled invoice as a valid document — disclose
  // the cancellation and offer the storno instead.
  const stornoId = invoice?.cancelled_by_invoice ?? null;
  const invoiceIsCancelled = !!stornoId;
  const { data: storno } = useCommissioningInvoicesRetrieve(stornoId!, {
    query: { enabled: !!stornoId },
  });

  const deliveryNoteRef = orderContents.find((i) => i.delivery_note_id);
  const invoiceRef = orderContents.find((i) => i.invoice_id);

  return (
    <Row gutter={[24, 24]} style={{ marginTop: 24 }}>
      <Col xs={24}>
        <Card title={t("customer.documents")}>
          <Space size="middle">
            <Button
              icon={<FilePdfOutlined />}
              disabled={!deliveryNote?.file}
              type="primary"
              onClick={() =>
                deliveryNote?.file &&
                window.open(deliveryNote.file, "_blank", "noopener,noreferrer")
              }
            >
              <DownloadOutlined /> {t("customer.delivery_note")}
              {deliveryNoteId && (
                <Text
                  type="secondary"
                  style={{
                    color: "var(--color-bg-base)",
                    marginLeft: 4,
                    fontSize: 12,
                  }}
                >
                  #{String(deliveryNoteRef?.delivery_note_prefix ?? "")}
                  {String(deliveryNoteRef?.delivery_note_number ?? "")}
                </Text>
              )}
            </Button>
            <Button
              icon={<FilePdfOutlined />}
              disabled={!invoice?.file || invoiceIsCancelled}
              type="primary"
              onClick={() =>
                !invoiceIsCancelled &&
                invoice?.file &&
                window.open(invoice.file, "_blank", "noopener,noreferrer")
              }
            >
              <DownloadOutlined /> {t("customer.invoice")}
              {invoiceId && (
                <Text
                  type="secondary"
                  style={{
                    color: "var(--color-bg-base)",
                    marginLeft: 4,
                    fontSize: 12,
                  }}
                >
                  #{String(invoiceRef?.invoice_prefix ?? "")}
                  {String(invoiceRef?.invoice_number ?? "")}
                </Text>
              )}
            </Button>
            {invoiceIsCancelled && (
              <Space size="small">
                <Text type="danger" style={{ fontSize: 12 }}>
                  {t("customer.invoice_cancelled")}
                </Text>
                <Button
                  icon={<FilePdfOutlined />}
                  disabled={!storno?.file}
                  onClick={() =>
                    storno?.file &&
                    window.open(storno.file, "_blank", "noopener,noreferrer")
                  }
                >
                  <DownloadOutlined /> {t("customer.storno")}
                  {storno?.invoice_number && (
                    <Text type="secondary" style={{ marginLeft: 4, fontSize: 12 }}>
                      #{String(storno.prefix ?? "")}
                      {String(storno.invoice_number ?? "")}
                    </Text>
                  )}
                </Button>
              </Space>
            )}
          </Space>
        </Card>
      </Col>
    </Row>
  );
}
