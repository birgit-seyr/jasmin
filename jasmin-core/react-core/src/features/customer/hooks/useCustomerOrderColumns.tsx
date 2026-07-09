import { EditOutlined } from "@ant-design/icons";
import { Button, Space } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useCurrency } from "@hooks/configuration/useCurrency";
import { useNumberFormat } from "@hooks/useNumberFormat";
import { useSizeOptions } from "@hooks/useSizeOptions";
import { useUnitOptions } from "@hooks/useUnitOptions";
import OrderAmountCell from "@features/customer/components/OrderAmountCell";
import type {
  CustomerOrderTableRow,
  StockError,
} from "@features/customer/types";

type TierPriceKey = "price_1" | "price_2" | "price_3";

interface Params {
  tableData: CustomerOrderTableRow[];
  finalTiers: number[];
  orderAmounts: Record<string, number>;
  editMode: boolean;
  saving: boolean;
  isReadOnly: boolean;
  /** Whole order is finalized / already has a delivery note → no edit toggle. */
  orderLocked: boolean;
  /** Per-offer insufficient-stock errors from the last save, keyed by offer id. */
  stockErrors: Record<string, StockError>;
  onAmountChange: (offerId: string, value: number | null) => void;
  onEnterEdit: () => void;
  onCancelEdit: () => void;
  onSaveAll: (rows: CustomerOrderTableRow[]) => void;
}

export function useCustomerOrderColumns({
  tableData,
  finalTiers,
  orderAmounts,
  editMode,
  saving,
  isReadOnly,
  orderLocked,
  stockErrors,
  onAmountChange,
  onEnterEdit,
  onCancelEdit,
  onSaveAll,
}: Params) {
  const { t } = useTranslation();
  const { formatCurrency } = useCurrency();
  const { format } = useNumberFormat();
  const { getUnitLabel } = useUnitOptions();
  const { getSizeLabel } = useSizeOptions();

  const activePriceTiers = useMemo(() => {
    return finalTiers
      .map((tier, index) => {
        // Tiers beyond the third have no matching price_N field on the row
        // models; their lookup stays undefined and they filter out below.
        const key = `price_${index + 1}` as TierPriceKey;
        const hasData = tableData.some(
          (row) => row[key] != null && Number(row[key]) !== 0,
        );
        return hasData ? { tier, index, key } : null;
      })
      .filter(
        (entry): entry is { tier: number; index: number; key: TierPriceKey } =>
          entry !== null,
      );
  }, [tableData, finalTiers]);

  return useMemo(() => {
    const cols: ColumnsType<CustomerOrderTableRow> = [
      {
        title: t("customer.article"),
        dataIndex: "offer_share_article_name",
        key: "share_article_name",
        render: (name: string | null | undefined, record) => {
          const size = record.size;
          const suffix = size && size !== "M" ? `, ${getSizeLabel(size)}` : "";
          return `${name ?? record.share_article_name ?? ""}${suffix}`;
        },
      },
      {
        title: t("customer.description"),
        key: "description",
        render: (_: unknown, record) => {
          const sort = record.sort;
          // Only the Offer-fallback rows carry a description; backend list
          // items don't expose one.
          const description =
            "description" in record ? record.description : undefined;
          return [sort, description].filter(Boolean).join(" ") || "-";
        },
      },
      {
        title: t("customer.per_pu"),
        dataIndex: "amount_per_pu",
        key: "amount_per_pu",
        align: "right" as const,
        render: (val: string | null, record) => {
          const unit = record.unit;
          return val
            ? `${format(Number(val), 2)} ${getUnitLabel(unit ?? "")}/${t("commissioning.pu")}`
            : "-";
        },
      },
    ];

    for (const { tier, key } of activePriceTiers) {
      cols.push({
        title: `${t("commissioning.tier", { tier })} `,
        dataIndex: key,
        key,
        align: "right" as const,
        render: (price: string | null | undefined, record) => {
          const unit = record.unit;
          return price && Number(price)
            ? `${formatCurrency(Number(price))}/${getUnitLabel(unit ?? "")}`
            : "-";
        },
      });
    }

    // The order-amount column is a single edit surface: one header toggle drives
    // the whole column. View mode shows an "Aktualisieren" button; edit mode
    // swaps it for a bulk Save + Cancel. Hidden entirely once the order is
    // frozen (past/closed week or finalized order).
    const canEdit = !isReadOnly && !orderLocked;
    cols.push({
      title: (
        <div className="order-col-header">
          <span>{t("customer.order_amount")}</span>
          {canEdit && (
            <Space size={4} className="order-col-header-actions">
              {editMode ? (
                <>
                  <Button
                    type="primary"
                    size="small"
                    className="dark-green-button"
                    loading={saving}
                    onClick={() => onSaveAll(tableData)}
                  >
                    {t("common.save")}
                  </Button>
                  <Button size="small" onClick={onCancelEdit} disabled={saving}>
                    {t("common.cancel")}
                  </Button>
                </>
              ) : (
                <Button
                  size="small"
                  icon={<EditOutlined />}
                  onClick={onEnterEdit}
                >
                  {t("customer.update")}
                </Button>
              )}
            </Space>
          )}
        </div>
      ),
      key: "order_col",
      align: "center" as const,
      width: 260,
      onCell: () => ({
        style: {
          backgroundColor: isReadOnly ? "var(--color-bg-subtle)" : "#e6f7e6",
          paddingLeft: 4,
          paddingRight: 4,
        },
      }),
      onHeaderCell: () => ({
        style: {
          backgroundColor: isReadOnly ? "var(--color-bg-subtle)" : "#e6f7e6",
          paddingLeft: 4,
          paddingRight: 4,
        },
      }),
      render: (_: unknown, record) => (
        <OrderAmountCell
          record={record}
          orderAmounts={orderAmounts}
          editMode={editMode}
          saving={saving}
          isReadOnly={isReadOnly}
          stockError={stockErrors[record.id as string]}
          onAmountChange={onAmountChange}
          onSubmit={() => onSaveAll(tableData)}
        />
      ),
    });

    return cols;
  }, [
    t,
    formatCurrency,
    getUnitLabel,
    getSizeLabel,
    activePriceTiers,
    tableData,
    orderAmounts,
    editMode,
    saving,
    isReadOnly,
    orderLocked,
    stockErrors,
    onAmountChange,
    onEnterEdit,
    onCancelEdit,
    onSaveAll,
    format,
  ]);
}
