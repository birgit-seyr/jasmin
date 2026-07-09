import type { ColumnsType } from "antd/es/table";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useCurrency } from "@hooks/configuration/useCurrency";
import { useNumberFormat } from "@hooks/useNumberFormat";
import { useVegetableSizeOptions } from "@hooks/useVegetableSizeOptions";
import { useUnitOptions } from "@hooks/useUnitOptions";
import { computeLineNetto } from "@shared/utils/lineNetto";
import type { OtherArticleRow } from "@features/customer/types";

/**
 * Read-only columns for the "other articles" table on the customer order page —
 * order-content lines with NO offer (office-added directly). Unlike the offers
 * table these carry a raw amount in the unit, a per-unit price and a rabatt, so
 * they get their own fitted columns instead of being squeezed into the offers
 * cell. The net line total mirrors the canonical line-netto math.
 */
export function useOtherArticleColumns() {
  const { t } = useTranslation();
  const { formatCurrency } = useCurrency();
  const { format } = useNumberFormat();
  const { getUnitLabel } = useUnitOptions();
  const { getVegetableSizeLabel } = useVegetableSizeOptions();

  return useMemo<ColumnsType<OtherArticleRow>>(() => {
    return [
      {
        title: t("customer.article"),
        dataIndex: "share_article_name",
        key: "share_article_name",
        render: (name: string | null, record) => {
          const size = record.size;
          const suffix = size && size !== "M" ? `, ${getVegetableSizeLabel(size)}` : "";
          return `${name ?? ""}${suffix}`;
        },
      },
      {
        title: t("customer.description"),
        key: "description",
        render: (_: unknown, record) => record.sort || "-",
      },
      {
        title: t("customer.amount"),
        key: "amount",
        align: "right" as const,
        render: (_: unknown, record) => {
          const amount = record.amount;
          const unit = record.unit;
          return amount != null
            ? `${format(Number(amount), 2)} ${getUnitLabel(unit ?? "")}`
            : "-";
        },
      },
      {
        title: t("customer.price_per_unit"),
        dataIndex: "price_per_unit",
        key: "price_per_unit",
        align: "right" as const,
        render: (val: string | null, record) => {
          const unit = record.unit;
          return val != null
            ? `${formatCurrency(Number(val))}/${getUnitLabel(unit ?? "")}`
            : "-";
        },
      },
      {
        title: t("customer.rabatt"),
        dataIndex: "rabatt",
        key: "rabatt",
        align: "right" as const,
        render: (val: string | null) =>
          val ? `${format(Number(val), 0)} %` : "-",
      },
      {
        title: t("customer.total"),
        key: "total",
        align: "right" as const,
        render: (_: unknown, record) =>
          formatCurrency(
            computeLineNetto({
              amount: record.amount,
              price_per_unit: record.price_per_unit,
              rabatt: record.rabatt,
            }),
          ),
      },
    ];
  }, [t, formatCurrency, format, getUnitLabel, getVegetableSizeLabel]);
}
