import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { useTenant } from "@hooks/configuration/useTenant";
import { useNumberFormat } from "@hooks/useNumberFormat";
import { useSizeOptions } from "@hooks/useSizeOptions";
import { useUnitOptions } from "@hooks/useUnitOptions";

interface AmountUnitSizeConfig {
  overrides?: Record<string, Record<string, unknown>>;
  showAmount?: boolean;
}

export const useAmountUnitSizeColumns = (config: AmountUnitSizeConfig = {}) => {
  const { overrides = {}, showAmount = true } = config;

  const { getSetting } = useTenant();
  const showSizeColumn = getSetting("show_size_column");

  const { t } = useTranslation();
  const { unitOptions, getUnitLabel } = useUnitOptions();
  const { sizeOptions, getSizeLabel } = useSizeOptions();
  const { format } = useNumberFormat();

  const amountUnitSizeColumns = useMemo<
    EditableColumnConfig<TableRecord>[]
  >(() => {
    const defaultColumns: EditableColumnConfig<TableRecord>[] = [];

    defaultColumns.push(
      {
        title: t("commissioning.unit"),
        dataIndex: "unit",
        key: "unit",
        inputType: "select",
        required: true,
        align: "center",
        fixed: true,
        options: unitOptions,
        render: (value: unknown) => getUnitLabel(value as string),
        onFieldChange: overrides.unit
          ?.onFieldChange as EditableColumnConfig<TableRecord>["onFieldChange"],
        ...overrides.unit,
      },
      {
        title: t("commissioning.size"),
        dataIndex: "size",
        key: "size",
        inputType: "select",
        required: false,
        hidden: !showSizeColumn,
        width: "7em",
        align: "center",
        fixed: true,
        options: sizeOptions,
        render: (value: unknown) => getSizeLabel(value as string),
        ...overrides.size,
      },
    );
    // Conditionally add amount column based on showAmount
    if (showAmount) {
      // Resolve overrides first so the default render below uses the
      // *final* inputType (callers may swap "positive_integer" for a
      // decimal flavour). Without an explicit render, Ant Table prints
      // the raw record value — which leaks "98.00" (Decimal string from
      // the PATCH response) until the next GET reformats it to 98. The
      // render below routes display through `format(value, decimals)`
      // so the cell stays locale-correct AND stable across that cycle.
      const merged: EditableColumnConfig<TableRecord> = {
        title: t("commissioning.amount"),
        dataIndex: "amount",
        key: "amount",
        inputType: "positive_integer",
        required: true,
        align: "center",
        width: "8em",
        suffix: (overrides.amount?.suffix as string) || undefined,
        ...overrides.amount,
      };
      if (!merged.render) {
        const it = merged.inputType ?? "positive_integer";
        const defaultDecimals = it.includes("decimal3")
          ? 3
          : it.includes("decimal2")
            ? 2
            : it.includes("decimal1")
              ? 1
              : 0;
        merged.render = (value: unknown) => {
          if (value === null || value === undefined || value === "") return "";
          const n = Number(value);
          if (!Number.isFinite(n)) return "";
          return format(n, defaultDecimals);
        };
      }
      defaultColumns.push(merged);
    }

    return defaultColumns;
  }, [unitOptions, sizeOptions, t, overrides, showAmount, showSizeColumn, getUnitLabel, getSizeLabel, format]);

  return { amountUnitSizeColumns };
};
