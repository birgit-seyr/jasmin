/**
 * Column factory for the Offers page — base columns plus the tenant-
 * configurable price-tier column group (incl. the tier-2/3 auto-fill
 * from the offer group's rabatt factors). The page supplies the data
 * sources (from ``useOffersData``); everything column-shaped lives
 * here.
 */

import { useMemo, useRef, type Key } from "react";
import { useTranslation } from "react-i18next";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { ToolTipIcon } from "@shared/ui";
import { editableOnlyOnCreate, renderNumber } from "@shared/utils";
import { parseDecimalInput } from "@shared/utils/numberFormat";
import { useCurrency } from "@hooks/configuration/useCurrency";
import type { useOffersData } from "../useOffersData";
import { useCrates } from "../useCrates";
import { useOfferTiers } from "../useOfferTiers";
import { useNumberFormat } from "@hooks/useNumberFormat";
import { useFinalColumn } from "./useFinalColumn";
import { useNoteColumn } from "@hooks/columns/useNoteColumn";
import { useAmountUnitSizeColumns } from "./useAmountUnitSizeColumns";
import { useShareArticleColumn } from "./useShareArticleColumn";
import { useWashingCleaningColumns } from "./useWashingCleaningColumns";

type OffersData = ReturnType<typeof useOffersData>;

/** A tier price: the base less the offer group's discount percent, in cents. */
const discountedPrice = (base: number, discountPercent: number): number =>
  Math.round(base * (100 - discountPercent)) / 100;

export function useOffersColumns({
  shareArticleFilters,
  shareArticles,
  currentOfferGroup,
  selectedOfferGroup,
}: {
  shareArticleFilters: OffersData["shareArticleFilters"];
  shareArticles: OffersData["shareArticles"];
  currentOfferGroup: OffersData["currentOfferGroup"];
  selectedOfferGroup: string | null;
}) {
  const { t } = useTranslation();
  const { crates } = useCrates();
  const { currencySymbol, formatCurrency } = useCurrency();
  const { format } = useNumberFormat();
  const { washingCleaningColumns } = useWashingCleaningColumns();
  const { noteColumn } = useNoteColumn();

  // Tenant-configured price tiers (shared with the orders + offer-group
  // tier columns via useOfferTiers).
  const finalTiers = useOfferTiers();
  // The tier-1 price each row's lower tiers were last derived from.
  const tierOneDerivedFromRef = useRef(new Map<Key, number>());

  const { shareArticleColumn, handleUnitChange } = useShareArticleColumn({
    filters: shareArticleFilters,
    showFruitsAndVegs: true,
    autofillContext: "reseller",
    overrides: {
      render: (text: string, record: TableRecord) => {
        if (record.forecast_exists) {
          return <span className="text-success text-bold">{text}</span>;
        }
        return text;
      },
    },
  });
  const { finalColumn } = useFinalColumn({
    tooltipTitle: t("tooltip.final_column_offers"),
  });

  const { amountUnitSizeColumns } = useAmountUnitSizeColumns({
    showAmount: false,
    overrides: {
      unit: {
        disabled: editableOnlyOnCreate,
        onFieldChange: handleUnitChange,
      },
      size: {
        disabled: editableOnlyOnCreate,
      },
    },
  });

  const tierColumns = useMemo(() => {
    const result = [
      {
        title: (
          <>
            {t("commissioning.price_per_unit")}
            <ToolTipIcon title={t("tooltip.price_per_unit_offers")} />
          </>
        ),
        children: finalTiers.map((tier, index) => {
          const column: EditableColumnConfig<TableRecord> = {
            title: t("commissioning.tier", { tier }) || `T${tier}`,
            dataIndex: `price_${index + 1}`,
            key: `price_${index + 1}`,
            inputType: "positive_decimal2",
            required: false,
            align: "center",
            width: "6em",
            suffix: currencySymbol,
            disabled: (record: TableRecord) => {
              return record.is_finalized === true;
            },
            render: (_: unknown, record: TableRecord) => {
              const currentPrice = record[
                `price_${index + 1}`
              ] as unknown as number;
              const displayPrice = formatCurrency(
                currentPrice ? Number(currentPrice) : 0,
              );

              const shareArticle = shareArticles.find(
                (sa) => sa.value === record.share_article,
              );

              let defaultPrice = 0;
              if (shareArticle && record.unit) {
                const unitUpper = (record.unit as string).toUpperCase();
                const shareArticleFields = shareArticle as unknown as Record<
                  string,
                  unknown
                >;

                switch (unitUpper) {
                  case "KG":
                    defaultPrice =
                      (shareArticleFields[
                        `net_price_for_orders_kg_${index + 1}`
                      ] as number) || 0;
                    break;
                  case "PCS":
                  case "PIECES":
                    defaultPrice =
                      (shareArticleFields[
                        `net_price_for_orders_pieces_${index + 1}`
                      ] as number) || 0;
                    break;
                  case "BUNCH":
                    defaultPrice =
                      (shareArticleFields[
                        `net_price_for_orders_bunch_${index + 1}`
                      ] as number) || 0;
                    break;
                }
              }

              const isModified =
                currentPrice &&
                defaultPrice &&
                Math.abs(Number(currentPrice) - Number(defaultPrice)) > 0.01;

              return (
                <span
                  style={{
                    color: isModified ? "orange" : "inherit",
                    fontWeight: isModified ? "bold" : "normal",
                  }}
                >
                  {displayPrice}
                </span>
              );
            },
          };

          if (index === 0) {
            // Tiers 2 and 3 follow tier 1 at the offer group's discounts
            // (rabatt_price_tier_N is a percent off the base: 10 % of 1.00
            // gives 0.90). This runs on every keystroke, so a tier keeps
            // following while it is empty or holds what tier 1 gave it —
            // as last typed, or as saved — and stays once the office types
            // a price of its own.
            column.onFieldChange = (
              value: unknown,
              record: TableRecord,
              form: {
                getFieldValue: (name: string) => unknown;
                setFieldValue: (name: string, value: unknown) => void;
              },
            ): Record<string, unknown> | undefined => {
              if (!selectedOfferGroup) return;
              const price1 = parseDecimalInput(value);
              if (price1 === null) return;

              const derivedFrom = [
                tierOneDerivedFromRef.current.get(record.key),
                parseDecimalInput(record.price_1),
              ].filter((base): base is number => base != null);
              for (const tier of [2, 3] as const) {
                const discount = Number(
                  currentOfferGroup?.[`rabatt_price_tier_${tier}`],
                );
                if (!discount) continue;
                const field = `price_${tier}`;
                const current = parseDecimalInput(form.getFieldValue(field));
                const followsTierOne =
                  !current ||
                  derivedFrom.some(
                    (base) =>
                      Math.abs(current - discountedPrice(base, discount)) <
                      0.005,
                  );
                if (followsTierOne) {
                  form.setFieldValue(
                    field,
                    discountedPrice(price1, discount).toFixed(2),
                  );
                }
              }
              tierOneDerivedFromRef.current.set(record.key, price1);
            };
          }

          return column;
        }),
      },
    ];

    return result;
  }, [
    finalTiers,
    t,
    selectedOfferGroup,
    currencySymbol,
    formatCurrency,
    shareArticles,
    currentOfferGroup,
  ]);

  const columns = useMemo<EditableColumnConfig<TableRecord>[]>(() => {
    const baseColumns = [
      finalColumn,
      ...washingCleaningColumns,
      {
        ...shareArticleColumn,
        disabled: editableOnlyOnCreate,
      },
      ...amountUnitSizeColumns,
      {
        title: <>{t("commissioning.sort")}</>,
        dataIndex: "sort",
        key: "sort",
        inputType: "text",
        disabled: (record: TableRecord) =>
          (record.amount_ordered as number) > 0 || record.is_finalized === true,
        required: false,
        width: "10em",
      },
      {
        title: <>{t("commissioning.description")}</>,
        dataIndex: "description",
        key: "description",
        inputType: "text",
        required: false,
        disabled: (record: TableRecord) =>
          (record.amount_ordered as number) > 0 || record.is_finalized === true,
        width: "12em",
      },
      {
        title: t("commissioning.amount_per_pu"),
        dataIndex: "amount_per_pu",
        key: "amount_per_pu",
        inputType: "positive_decimal2",
        required: true,
        align: "center",
        width: "6em",
        disabled: (record: TableRecord) =>
          (record.amount_ordered as number) > 0 || record.is_finalized === true,
        render: renderNumber(format, 2),
      },
      {
        title: <>{t("commissioning.used_crate")}</>,
        dataIndex: "used_crate_name",
        key: "used_crate_name",
        inputType: "select",
        // ``used_crate`` is nullable (per-offer override of the article's
        // default crate). ``useCrates`` already includes a null "clear" option;
        // required:false lets the office actually clear it back to the default.
        options: crates,
        required: false,
        disabled: (record: TableRecord) =>
          (record.amount_ordered as number) > 0 || record.is_finalized === true,
        width: "8em",
        foreignKey: {
          valueField: "used_crate",
          displayField: "used_crate_name",
        },
      },

      {
        title: (
          <>
            {t("commissioning.available_pu")}{" "}
            <ToolTipIcon title={t("tooltip.available_pu_offers")} />
          </>
        ),
        dataIndex: "amount",
        key: "amount",
        width: "8em",
        inputType: "positive_decimal3",
        required: true,
        align: "center",
        suffix: t("commissioning.pu"),
        render: (_: unknown, record: TableRecord) => {
          const amount = record.amount ? Number(record.amount) : 0;
          const amountClass =
            amount === 0 ? "amount-none-left" : "amount-left";
          // An order leaves a fraction of a PU behind; show the digits it
          // has (up to the column's 3), so "2,500" can't read as thousands.
          const fractionDigits =
            String(Number(amount.toFixed(3))).split(".")[1]?.length ?? 0;

          return (
            <span className={amountClass}>
              {format(amount, fractionDigits)} {t("commissioning.pu")}
            </span>
          );
        },
      },
      {
        title: (
          <div className="tiny-title">
            {t("commissioning.already_ordered_pu")}
          </div>
        ),
        dataIndex: "amount_ordered",
        key: "amount_ordered",
        align: "center",
        width: "6em",
        disabled: true,
        render: (_: unknown, record: TableRecord) => {
          if (record.amount_ordered === undefined) return "";

          const amountPerPu = Number(record.amount_per_pu);
          if (!amountPerPu) {
            return (
              <div className="read-only-amounts-planning">
                {format(Number(record.amount_ordered), 1)}{" "}
              </div>
            );
          }

          const calculatedValue = Number(record.amount_ordered) / amountPerPu;

          return (
            <div className="read-only-amounts-planning">
              {format(calculatedValue, 1)}{" "}
            </div>
          );
        },
      },
      ...tierColumns,
      {
        ...noteColumn,
        inputType: "optional",
        width: "25em",
      },
    ];

    return [...baseColumns] as EditableColumnConfig<TableRecord>[];
  }, [
    t,
    amountUnitSizeColumns,
    shareArticleColumn,
    tierColumns,
    finalColumn,
    crates,
    noteColumn,
    washingCleaningColumns,
    format,
  ]);

  return { columns };
}
