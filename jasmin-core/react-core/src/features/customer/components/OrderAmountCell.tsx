import { Input, Space, Tag, Typography } from "antd";
import { useTranslation } from "react-i18next";
import type {
  CustomerOrderTableRow,
  StockError,
} from "@features/customer/types";

const { Text } = Typography;

interface Props {
  record: CustomerOrderTableRow;
  orderAmounts: Record<string, number>;
  editMode: boolean;
  saving: boolean;
  isReadOnly: boolean;
  /** Set when the last save rejected this row for insufficient stock. */
  stockError?: StockError;
  onAmountChange: (offerId: string, value: number | null) => void;
  onSubmit: () => void;
}

export default function OrderAmountCell({
  record,
  orderAmounts,
  editMode,
  saving,
  isReadOnly,
  stockError,
  onAmountChange,
  onSubmit,
}: Props) {
  const { t } = useTranslation();
  // Table rows always carry the offer id (it's the rowKey); the base list
  // item type keeps id nullable for placeholder-free shapes.
  const offerId = record.id as string;
  const orderContentId = record.order_content_id;
  const ordered = record.ordered_amount_num;
  const orderFinalized = record.order_is_finalized;

  const amountTag = (color?: string) => (
    <Tag color={color} className="order-amount-tag">
      {Math.round(ordered ?? 0)} {t("commissioning.pu")}
    </Tag>
  );

  // Frozen rows — the week is over/closed, or the order is finalized — are
  // never editable, even while the rest of the column is in edit mode.
  if (isReadOnly || (orderFinalized && orderContentId)) {
    if (ordered != null && ordered > 0) {
      return amountTag(orderFinalized ? "green" : undefined);
    }
    return <Text type="secondary">-</Text>;
  }

  // Edit mode: the whole column is inputs. Seed with the current ordered PU
  // amount (empty for a not-yet-ordered offer); a pending edit wins. A row the
  // last save rejected for stock goes red with a tiny ceiling tag until edited.
  if (editMode) {
    const seeded = ordered != null ? Math.round(ordered) : "";
    const value = offerId in orderAmounts ? orderAmounts[offerId] || "" : seeded;
    const input = (
      <Input
        value={value}
        status={stockError ? "error" : undefined}
        onChange={(e) => onAmountChange(offerId, Number(e.target.value) || 0)}
        onPressEnter={onSubmit}
        disabled={saving}
        style={{ width: "80px" }}
        suffix={t("commissioning.pu")}
        aria-label={t("customer.order_amount")}
      />
    );
    if (!stockError) return input;
    // ``available`` is the VPE ceiling this row can be set to (remaining stock
    // + this reseller's own already-ordered amount) — show it directly.
    const maxPu = Math.floor(stockError.available);
    return (
      <Space direction="vertical" size={2} align="center">
        {input}
        <Tag color="red" className="order-stock-error-tag">
          {t("customer.insufficient_stock_tag", { count: maxPu })}
        </Tag>
      </Space>
    );
  }

  // View mode: read-only display of the placed amount (dash if nothing ordered).
  if (orderContentId && ordered != null && ordered > 0) {
    return amountTag();
  }
  return <Text type="secondary">-</Text>;
}
