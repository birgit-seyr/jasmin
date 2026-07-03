import { ShoppingCartOutlined } from "@ant-design/icons";
import { Button, Input, Space, Tag, Typography } from "antd";
import { useTranslation } from "react-i18next";
import type { CustomerOrderTableRow } from "@features/customer/types";

const { Text } = Typography;

interface Props {
  record: CustomerOrderTableRow;
  orderAmounts: Record<string, number>;
  submitting: Record<string, boolean>;
  isReadOnly: boolean;
  onAmountChange: (offerId: string, value: number | null) => void;
  onOrder: (record: CustomerOrderTableRow) => void;
  onUpdate: (record: CustomerOrderTableRow) => void;
}

export default function OrderAmountCell({
  record,
  orderAmounts,
  submitting,
  isReadOnly,
  onAmountChange,
  onOrder,
  onUpdate,
}: Props) {
  const { t } = useTranslation();
  // Table rows always carry the offer id (it's the rowKey); the base list
  // item type keeps id nullable for placeholder-free shapes.
  const offerId = record.id as string;
  const orderContentId = record.order_content_id;
  const ordered = record.ordered_amount_num;
  const orderFinalized = record.order_is_finalized;

  if (isReadOnly) {
    if (ordered != null && ordered > 0) {
      return (
        <Tag className="order-amount-tag">
          {Math.round(ordered)} {t("commissioning.pu")}
        </Tag>
      );
    }
    return <Text type="secondary">-</Text>;
  }

  if (orderFinalized && orderContentId) {
    return (
      <Tag color="green" className="order-amount-tag">
        {Math.round(ordered ?? 0)} {t("commissioning.pu")}
      </Tag>
    );
  }

  if (orderContentId) {
    const currentPuAmount = ordered != null ? Math.round(ordered) : 0;
    const editAmount =
      offerId in orderAmounts ? orderAmounts[offerId] : currentPuAmount;
    return (
      <Space>
        <Input
          value={editAmount || ""}
          onChange={(e) =>
            onAmountChange(offerId, Number(e.target.value) || 0)
          }
          onPressEnter={() => onUpdate(record)}
          style={{ width: "80px" }}
          suffix={t("commissioning.pu")}
          aria-label={t("customer.order_amount")}
        />
        <Button
          type="primary"
          size="small"
          onClick={() => onUpdate(record)}
          loading={submitting[offerId]}
          className="dark-green-button"
        >
          {t("customer.update")}
        </Button>
      </Space>
    );
  }

  return (
    <Space>
      <Input
        value={orderAmounts[offerId] || ""}
        onChange={(e) => onAmountChange(offerId, Number(e.target.value) || 0)}
        onPressEnter={() => onOrder(record)}
        style={{ width: "80px" }}
        suffix={t("commissioning.pu")}
        aria-label={t("customer.order_amount")}
      />
      <Button
        type="primary"
        icon={<ShoppingCartOutlined />}
        onClick={() => onOrder(record)}
        loading={submitting[offerId]}
        size="small"
        className="dark-green-button"
      >
        {t("customer.add")}
      </Button>
    </Space>
  );
}
