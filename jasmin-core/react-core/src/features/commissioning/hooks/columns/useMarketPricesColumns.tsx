import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import ToolTipIcon from "@shared/ui/ToolTipIcon";
import { useCurrency } from "@hooks/configuration/useCurrency";
import { useUnitOptions } from "@hooks/useUnitOptions";
import type { MarketArticleOption } from "../useMarketArticles";
import { useIsActiveColumn } from "./useIsActiveColumn";

/**
 * Columns of the weekly market price list. The PLU's own fields come with
 * each price and are read-only here; a new row picks its PLU, which an
 * existing price keeps (it moves to another week by copying). A price that
 * changed since last week shows in bold.
 */
export const useMarketPricesColumns = ({
  marketArticles,
}: {
  marketArticles: MarketArticleOption[];
}) => {
  const { t } = useTranslation();
  const { currencySymbol, formatCurrency } = useCurrency();
  const { getUnitLabel } = useUnitOptions();
  const isActiveColumn = useIsActiveColumn();

  return useMemo<EditableColumnConfig<TableRecord>[]>(
    () => [
      isActiveColumn,
      {
        title: <>{t("commissioning.plu_number")}</>,
        dataIndex: "plu_number",
        key: "plu_number",
        readOnly: true,
        width: "5em",
        align: "right",
        sortable: true,
      },
      {
        title: <>{t("commissioning.market_label")}</>,
        dataIndex: "name",
        key: "name",
        inputType: "select",
        required: true,
        width: "16em",
        align: "left",
        options: marketArticles,
        foreignKey: { valueField: "market_article", displayField: "name" },
        disabled: (record: TableRecord) => record.key !== -1,
        sortable: true,
      },
      {
        title: <>{t("commissioning.sort")}</>,
        dataIndex: "sort",
        key: "sort",
        readOnly: true,
        width: "9em",
        align: "left",
      },
      {
        title: <>{t("commissioning.origin")}</>,
        dataIndex: "origin",
        key: "origin",
        inputType: "text",
        required: false,
        width: "9em",
        align: "left",
      },
      {
        title: <>{t("commissioning.unit")}</>,
        dataIndex: "unit",
        key: "unit",
        readOnly: true,
        width: "5em",
        align: "center",
        render: (value: unknown) => (value ? getUnitLabel(value as string) : ""),
      },
      {
        title: (
          <>
            {t("commissioning.gross_price")}
            <ToolTipIcon title={t("commissioning.price_changed_tooltip")} />
          </>
        ),
        dataIndex: "gross_price",
        key: "gross_price",
        inputType: "positive_decimal2",
        required: true,
        suffix: currencySymbol,
        width: "9em",
        align: "right",
        render: (value: unknown, record: TableRecord) => {
          if (value == null || value === "") return "";
          const price = formatCurrency(Number(value));
          return record.is_changed ? <strong>{price}</strong> : price;
        },
      },
      {
        title: <>{t("commissioning.previous_gross_price")}</>,
        dataIndex: "previous_gross_price",
        key: "previous_gross_price",
        readOnly: true,
        width: "9em",
        align: "right",
        render: (value: unknown) =>
          value == null ? "" : formatCurrency(Number(value)),
      },
      {
        title: <>{t("commissioning.market_product_group")}</>,
        dataIndex: "product_group_name",
        key: "product_group_name",
        readOnly: true,
        width: "10em",
        align: "left",
        sortable: true,
      },
    ],
    [
      isActiveColumn,
      t,
      marketArticles,
      getUnitLabel,
      currencySymbol,
      formatCurrency,
    ],
  );
};
