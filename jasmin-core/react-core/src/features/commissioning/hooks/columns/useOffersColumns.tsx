/**
 * Column factory for the Offers page — base columns plus the tenant-
 * configurable price-tier column group (incl. the tier-2/3 auto-fill
 * from the offer group's rabatt factors). The page supplies the data
 * sources (from ``useOffersData``); everything column-shaped lives
 * here.
 */

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import { ToolTipIcon } from "@shared/ui";
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
  const { currencySymbol } = useCurrency();
  const { format } = useNumberFormat();
  const { washingCleaningColumns } = useWashingCleaningColumns();
  const { noteColumn } = useNoteColumn();

  // Tenant-configured price tiers (shared with the orders + offer-group
  // tier columns via useOfferTiers).
  const finalTiers = useOfferTiers();

  const { shareArticleColumn, handleUnitChange } = useShareArticleColumn({
    filters: shareArticleFilters,
    showFruitsAndVegs: true,
    articleDefaults: "reseller",
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
        disabled: (record: TableRecord) => {
          if (record.key != -1) return true;
        },
        onFieldChange: handleUnitChange,
      },
      size: {
        disabled: (record: TableRecord) => {
          if (record.key != -1) return true;
        },
      },
    },
  });

  const tierColumns = useMemo(() => {
    if (!finalTiers || finalTiers.length === 0) {
      return [];
    }

    const result = [
      {
        title: (
          <>
            {t("commissioning.price_per_unit")}
            <ToolTipIcon title={t("tooltip.price_per_unit_offers")} />
          </>
        ),
        children: finalTiers.map((tier, index) => {
          const column: any = {
            title: t("commissioning.tier", { tier }) || `T${tier}`,
            dataIndex: `price_${index + 1}`,
            key: `price_${index + 1}`,
            inputType: "positive_decimal2",
            required: false,
            align: "center",
            width: "6em",
            suffix: currencySymbol,
            disabled: (record: TableRecord) => {
              return record?.is_finalized === true;
            },
            render: (_: unknown, record: TableRecord) => {
              const currentPrice = record[
                `price_${index + 1}`
              ] as unknown as number;
              const displayPrice = currentPrice
                ? format(Number(currentPrice), 2)
                : format(0, 2);

              const shareArticle = shareArticles?.find(
                (sa) => sa.value === record.share_article,
              );

              let defaultPrice = 0;
              if (shareArticle && record.unit) {
                const unitUpper = (record.unit as string).toUpperCase();
                const saAny = shareArticle as unknown as Record<
                  string,
                  unknown
                >;

                switch (unitUpper) {
                  case "KG":
                    defaultPrice =
                      (saAny[
                        `net_price_for_orders_kg_${index + 1}`
                      ] as number) || 0;
                    break;
                  case "PCS":
                  case "PIECES":
                    defaultPrice =
                      (saAny[
                        `net_price_for_orders_pieces_${index + 1}`
                      ] as number) || 0;
                    break;
                  case "BUNCH":
                    defaultPrice =
                      (saAny[
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
                  {displayPrice} {currencySymbol}
                </span>
              );
            },
          };

          if (index === 0) {
            column.onFieldChange = (
              value: string,
              record: TableRecord,
              form: {
                getFieldsValue: () => Record<string, unknown>;
                setFieldValue: (name: string, value: unknown) => void;
              },
            ) => {
              if (!selectedOfferGroup || !value) return;

              const price1 = parseFloat(value);
              if (isNaN(price1)) return;

              const currentValues = form.getFieldsValue();

              if (currentOfferGroup?.rabatt_price_tier_2) {
                const shouldSetPrice2 =
                  !currentValues.price_2 || currentValues.price_2 === 0;
                if (shouldSetPrice2) {
                  // rabatt_price_tier_2 is a DISCOUNT percent (0–100) off the
                  // base price: tier price = price1 * (1 - rabatt/100). A 10%
                  // rabatt on a base of 1.00 yields 0.90, not 0.10.
                  const price2 = (
                    price1 *
                    (1 -
                      (currentOfferGroup.rabatt_price_tier_2 as number) / 100)
                  ).toFixed(2);
                  form.setFieldValue("price_2", price2);
                }
              }

              if (currentOfferGroup?.rabatt_price_tier_3) {
                const shouldSetPrice3 =
                  !currentValues.price_3 || currentValues.price_3 === 0;
                if (shouldSetPrice3) {
                  // Discount percent off the base — see price_2 above.
                  const price3 = (
                    price1 *
                    (1 -
                      (currentOfferGroup.rabatt_price_tier_3 as number) / 100)
                  ).toFixed(2);
                  form.setFieldValue("price_3", price3);
                }
              }
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
    shareArticles,
    currentOfferGroup,
    format,
  ]);

  const columns: any[] = useMemo(() => {
    const baseColumns = [
      finalColumn,
      ...washingCleaningColumns,
      {
        ...shareArticleColumn,
        disabled: (record: TableRecord) => record.key != -1,
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
        render: (_: unknown, record: TableRecord) => {
          if (
            record.amount_per_pu === null ||
            record.amount_per_pu === undefined ||
            record.amount_per_pu === ""
          )
            return "";
          const n = Number(record.amount_per_pu);
          return Number.isFinite(n) ? format(n, 2) : "";
        },
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
        inputType: "positive_integer",
        required: true,
        align: "center",
        suffix: t("commissioning.pu"),
        render: (_: unknown, record: TableRecord) => {
          const amount = record.amount ? Number(record.amount) : 0;
          const color = amount === 0 ? "darkred" : "darkgreen";

          return (
            <span style={{ color }}>
              {format(amount, 0)} {t("commissioning.pu")}
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
          if (!amountPerPu || amountPerPu === 0 || isNaN(amountPerPu)) {
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

    return [...baseColumns];
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
