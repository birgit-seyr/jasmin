import type { ColumnsType } from "antd/es/table";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useCurrency } from "@hooks/configuration/useCurrency";
import { useNumberFormat } from "@hooks/useNumberFormat";
import { useSizeOptions } from "@hooks/useSizeOptions";
import { useUnitOptions } from "@hooks/useUnitOptions";
import OrderAmountCell from "@features/customer/components/OrderAmountCell";
import type { CustomerOrderTableRow } from "@features/customer/types";

type TierPriceKey = "price_1" | "price_2" | "price_3";

interface Params {
  tableData: CustomerOrderTableRow[];
  finalTiers: number[];
  orderAmounts: Record<string, number>;
  submitting: Record<string, boolean>;
  isReadOnly: boolean;
  onAmountChange: (offerId: string, value: number | null) => void;
  onOrder: (record: CustomerOrderTableRow) => void;
  onUpdate: (record: CustomerOrderTableRow) => void;
}

export function useCustomerOrderColumns({
  tableData,
  finalTiers,
  orderAmounts,
  submitting,
  isReadOnly,
  onAmountChange,
  onOrder,
  onUpdate,
}: Params) {
  const { t } = useTranslation();
  const { currencySymbol } = useCurrency();
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
            ? `${format(Number(price), 2)} ${currencySymbol}/${getUnitLabel(unit ?? "")}`
            : "-";
        },
      });
    }

    cols.push({
      title: t("customer.order_amount"),
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
          submitting={submitting}
          isReadOnly={isReadOnly}
          onAmountChange={onAmountChange}
          onOrder={onOrder}
          onUpdate={onUpdate}
        />
      ),
    });

    return cols;
  }, [
    t,
    currencySymbol,
    getUnitLabel,
    getSizeLabel,
    activePriceTiers,
    orderAmounts,
    submitting,
    isReadOnly,
    onAmountChange,
    onOrder,
    onUpdate,
    format,
  ]);
}
