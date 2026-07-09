import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import DiffCell from "@shared/ui/DiffCell";
import type {
  EditableColumnConfig,
  SelectOption,
} from "@shared/tables/BasicEditableTable/types";
import { itemLineNetto, type LineNettoInput } from "@shared/utils/lineNetto";
import { editableOnlyOnCreate } from "@shared/utils";
import { useCurrency } from "@hooks/configuration/useCurrency";
import type { CrateOption } from "../useCrates";
import { useCrates } from "../useCrates";
import type { CrateOrderContentRow } from "../useOrdersData";
import { useNumberFormat } from "@hooks/useNumberFormat";
import { useNoteColumn } from "@hooks/columns/useNoteColumn";

 
type Rec = Record<string, any>;

interface CratesColumnOptions {
  disableCrateType?: (record: Record<string, unknown>) => boolean;
  columnsPrices?: unknown[];
  showNote?: boolean;
  without_price?: boolean;
  [key: string]: unknown;
}

export const useCratesColumns = (options: CratesColumnOptions = { without_price: false }) => {
  const { t } = useTranslation();
  const { crates } = useCrates({ includeNullOption: false, get_price_info: true });
  const { currencySymbol, formatCurrency } = useCurrency();
  const { format } = useNumberFormat();
  const { noteColumn } = useNoteColumn({ inputType: "optional" });

  const {
    disableCrateType = editableOnlyOnCreate,
    showNote = true,
    without_price = false,
    ...columnOverrides
  } = options;

  const handleCrateChange = useCallback(
    (crateValue: unknown, record: Record<string, unknown>, form: { setFieldsValue: (values: Record<string, unknown>) => void }) => {
      const selectedCrate = crates.find((c) => c.value === crateValue);
      if (!selectedCrate || !("id" in selectedCrate)) return {};

      const crateData = selectedCrate as CrateOption & { price?: number; tax_rate?: number };
      const price = Number(crateData.price) || 0;
      const taxRate = crateData.tax_rate;

      // The crate selection changed, so always overwrite price + tax with the
      // NEW crate's values — clearing them when the new crate has none. The
      // previous `!record.price_per_unit` guard left a prior crate's price in
      // place, so switching crates showed a stale / wrong price.
      form.setFieldsValue({
        price_per_unit: price > 0 ? price : null,
        tax_rate: taxRate !== undefined && taxRate !== null ? taxRate : null,
      });
      return {};
    },
    [crates],
  );

  const cratesColumns = useMemo<EditableColumnConfig<CrateOrderContentRow>[]>(() => {
    const baseColumns: EditableColumnConfig<CrateOrderContentRow>[] = [
      {
        title: t("commissioning.crate_type_name"),
        dataIndex: "crate_type_name",
        key: "crate_type_name",
        inputType: "select",
        required: true,
        align: "left",
        width: "16em",
        // CrateOption's union includes the null "clear" placeholder shape,
        // which SelectOption can't express (value: string | number) — same
        // widening as useShareArticleColumn's options.
        options: crates as unknown as SelectOption[],
        disabled: disableCrateType,
        onFieldChange: handleCrateChange,
        foreignKey: {
          valueField: "crate_type",
          displayField: "crate_type_name",
        },
        render: (value: unknown, _record: Rec) => (
          <div>
            <span>{value as string}</span>
          </div>
        ),
      },
      {
        title: t("commissioning.amount"),
        dataIndex: "amount",
        key: "amount",
        inputType: "negative_integer",
        required: true,
        align: "center",
        width: "8em",
        render: (value: unknown, record: Rec) => (
          <DiffCell
            value={value as string}
            differs={record.amount_differs as boolean | undefined}
            original={record.original_amount}
          />
        ),
      },
    ];

    if (!without_price) {
      baseColumns.push(
        {
          title: t("commissioning.single_price"),
          dataIndex: "price_per_unit",
          key: "price_per_unit",
          inputType: "positive_decimal2",
          required: false,
          suffix: currencySymbol,
          align: "center",
          width: "8em",
          render: (_: unknown, record: Rec) => (
            <DiffCell
              value={
                record.price_per_unit
                  ? formatCurrency(Number(record.price_per_unit))
                  : ""
              }
              differs={record.price_per_unit_differs as boolean | undefined}
              original={record.original_price_per_unit}
              formatOriginal={(o) => formatCurrency(Number(o))}
            />
          ),
        },
        {
          title: <>{t("commissioning.rabatt")}</>,
          dataIndex: "rabatt",
          key: "rabatt",
          inputType: "positive_integer",
          required: false,
          suffix: "%",
          align: "center",
          width: "7em",
          render: (_: unknown, record: Rec) => (
            <DiffCell
              value={record.rabatt ? `${record.rabatt} %` : ""}
              differs={record.rabatt_differs as boolean | undefined}
              original={record.original_rabatt}
              originalSuffix=" %"
            />
          ),
        },
        {
          title: <>{t("commissioning.line_netto")}</>,
          dataIndex: "line_netto",
          key: "line_netto",
          inputType: "positive_decimal2",
          required: false,
          readOnly: true,
          disabled: true,
          align: "right",
          width: "8em",
          render: (_: unknown, record: Rec) => {
            // Prefer the backend's canonical line_netto (parsed by
            // withLineTotals for fetched rows / the recomputed preview for
            // live edits); fall back to the shared inline computation only
            // when it's absent.
            const finalPrice = itemLineNetto(
              record as unknown as LineNettoInput,
            );
            return <span>{formatCurrency(finalPrice)}</span>;
          },
        },
        {
          title: (
 <span className="text-xs">{t("commissioning.ust")}</span>
          ),
          dataIndex: "tax_rate",
          key: "tax_rate",
          inputType: "positive_integer",
          required: false,
          // The crate's tax rate is authoritative — set on crate selection
          // (handleCrateChange) and locked, not user-editable.
          disabled: true,
          align: "center",
          width: "5em",
          render: (_: unknown, record: Rec) => (
            <div>
 <span className="text-xs">
                {record.tax_rate ? `${format(Number(record.tax_rate), 2)} %` : ""}
              </span>
            </div>
          ),
        }
      );
    }

    if (showNote) {
      // noteColumn is typed against TableRecord (required ``key``), while
      // CrateOrderContentRow's ``key`` is optional until EditableTable adds
      // it — safe to widen, the note cell never reads ``key``.
      baseColumns.push(
        noteColumn as unknown as EditableColumnConfig<CrateOrderContentRow>,
      );
    }

    return baseColumns.map((col) => ({
      ...col,
      ...(columnOverrides[col.key ?? ""] as
        | Partial<EditableColumnConfig<CrateOrderContentRow>>
        | undefined),
    }));
  }, [
    crates,
    t,
    disableCrateType,
    showNote,
    noteColumn,
    columnOverrides,
    currencySymbol,
    formatCurrency,
    format,
    handleCrateChange,
    without_price,
  ]);

  return {
    cratesColumns,
    crates,
  };
};
