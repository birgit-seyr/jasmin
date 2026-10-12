import { CheckOutlined } from "@ant-design/icons";
import { Tag } from "antd";
import { useTranslation } from "react-i18next";
import type { CombinedOrderOverview } from "@shared/api/generated/models";

interface InvoiceNumberCellProps {
  row: CombinedOrderOverview;
}

/**
 * The invoice number of an order overview row with its finalized mark. A
 * cancelled invoice carries its storno's number.
 */
export default function InvoiceNumberCell({ row }: InvoiceNumberCellProps) {
  const { t } = useTranslation();
  return (
    <>
      {row.has_finalized_invoice ? (
        <>
          <CheckOutlined aria-hidden className="icon-check-success" />
          <span className="sr-only">{t("commissioning.finalized")}</span>
        </>
      ) : (
        <span className="sr-only">{t("commissioning.not_finalized")}</span>
      )}
      {row.invoice_number}
      {row.invoice_cancelled_by ? (
        <Tag color="red" bordered={false}>
          {t("commissioning.storno_short")}
          {row.invoice_storno_number ? ` ${row.invoice_storno_number}` : ""}
        </Tag>
      ) : null}
    </>
  );
}
