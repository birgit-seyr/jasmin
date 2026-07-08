import type { ReactNode } from "react";
import { Typography } from "antd";
import type { TFunction } from "i18next";
import { isFieldDisabled } from "@shared/utils";
import { formatNumber } from "@shared/utils/numberFormat";
import type { EditableColumnConfig } from "@shared/tables/BasicEditableTable/types";

const { Text } = Typography;

export interface CurrencyPriceColumnOptions {
  title: ReactNode;
  dataIndex: string;
  currencySymbol: string;
  width?: string | number;
  required?: boolean;
  className?: string;
  /** Wrap the rendered value in <Text>. Defaults to true. */
  wrapInText?: boolean;
  /** BCP-47 locale tag used for number rendering. */
  locale?: string;
}

/**
 * Build a money column (decimal2 input + currency suffix + formatted render).
 * Used by all price modals.
 */
export function buildCurrencyPriceColumn({
  title,
  dataIndex,
  currencySymbol,
  width = "6em",
  required = false,
  className,
  wrapInText = true,
  locale,
}: CurrencyPriceColumnOptions): EditableColumnConfig {
  return {
    title,
    dataIndex,
    key: dataIndex,
    inputType: "decimal2", // allowing negatives for thinks like vouchers
    required,
    disabled: isFieldDisabled,
    width,
    align: "center",
    suffix: currencySymbol,
    className,
    render: (value: unknown) => {
      if (value == null) return null;
      // Sanctioned boundary cast: money cells carry decimal strings / numbers
      // on the wire; formatNumber's parameter is narrowed to that domain.
      const formatted = `${formatNumber(value as number | string, 2, locale)} ${currencySymbol}`;
      return wrapInText ? <Text>{formatted}</Text> : formatted;
    },
  };
}

export interface TaxRateColumnOptions {
  title?: ReactNode;
  /** Number of decimals to render (input is always positive_decimal2). Defaults to 2. */
  renderDecimals?: 0 | 2;
  width?: string | number;
  inputType?: "positive_decimal2" | "positive_integer";
  required?: boolean;
  /** BCP-47 locale tag used for number rendering. */
  locale?: string;
}

/**
 * Build a tax-rate column (decimal2 or integer input + " %" suffix).
 */
export function buildTaxRateColumn(
  t: TFunction,
  {
    title,
    renderDecimals = 2,
    width = "5.5em",
    inputType = "positive_decimal2",
    required = true,
    locale,
  }: TaxRateColumnOptions = {},
): EditableColumnConfig {
  return {
    title: title ?? <>{t("commissioning.tax_rate")}</>,
    dataIndex: "tax_rate",
    key: "tax_rate",
    inputType,
    required,
    disabled: isFieldDisabled,
    width,
    align: "center",
    suffix: " %",
    render: (value: unknown) =>
      value != null
        ? `${formatNumber(value as number | string, renderDecimals, locale)} %`
        : null,
  };
}
