/**
 * Column factory for the Forecast page. The page supplies the prebuilt
 * shared column refs (final / share-article / amount-unit-size / note),
 * the per-variation + offer-group child columns, the master ⇄ variation
 * checkbox sync handlers, the tenant flags, and the plot options; every
 * column shape lives here.
 */

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import type { PlotOption } from "../usePlots";

interface UseForecastColumnsArgs {
  isComponentReady: boolean;
  finalColumn: EditableColumnConfig<TableRecord>;
  shareArticleColumn: EditableColumnConfig<TableRecord>;
  amountUnitSizeColumns: EditableColumnConfig<TableRecord>[];
  noteColumn: EditableColumnConfig<TableRecord>;
  fruit_and_veg_shares_are_separate: boolean;
  shareTypeVariationsCount: number;
  // The per-variation / offer-group child columns are built in the page from
  // dynamic share-type-variation / offer-group lists. They're plain column
  // literals spread into `children` (which get cast on return), so they're
  // typed loosely here to avoid forcing the page's `.map()` memos to carry
  // full `EditableColumnConfig` literal types.
  shareVariationColumns: Record<string, unknown>[];
  shareTypeVariationsFruitsCount: number;
  shareVariationFruitsColumns: Record<string, unknown>[];
  onForAllVegChange: (value: unknown) => Record<string, unknown>;
  onForAllFruitChange: (value: unknown) => Record<string, unknown>;
  sells_to_resellers: boolean;
  offerGroupsCount: number;
  offerGroupColumns: Record<string, unknown>[];
  isResellerDisabled: (record: Record<string, unknown>) => boolean;
  has_markets: boolean;
  countPlots: number;
  plots: PlotOption[];
}

export function useForecastColumns({
  isComponentReady,
  finalColumn,
  shareArticleColumn,
  amountUnitSizeColumns,
  noteColumn,
  fruit_and_veg_shares_are_separate,
  shareTypeVariationsCount,
  shareVariationColumns,
  shareTypeVariationsFruitsCount,
  shareVariationFruitsColumns,
  onForAllVegChange,
  onForAllFruitChange,
  sells_to_resellers,
  offerGroupsCount,
  offerGroupColumns,
  isResellerDisabled,
  has_markets,
  countPlots,
  plots,
}: UseForecastColumnsArgs): EditableColumnConfig<TableRecord>[] {
  const { t } = useTranslation();

  return useMemo<EditableColumnConfig<TableRecord>[]>(() => {
    if (!isComponentReady) return [];

    return [
      finalColumn,
      {
        ...shareArticleColumn,
        disabled: (record: TableRecord) => record.key != -1,
      },
      ...amountUnitSizeColumns,
      ...(fruit_and_veg_shares_are_separate
        ? [
            ...(shareTypeVariationsCount > 1
              ? [
                  {
                    title: (
                      <span className="text-xs">
                        {t("commissioning.for_veg_shares")}
                      </span>
                    ),
                    key: "for_shares",
                    className: "column-group-start",
                    children: [
                      {
                        title: <>{t("commissioning.for_all")}</>,
                        dataIndex: "for_all_harvest_shares",
                        key: "for_all_harvest_shares",
                        inputType: "checkbox",
                        required: false,
                        className: "column-group-start",
                        onFieldChange: onForAllVegChange,
                      },
                      ...shareVariationColumns,
                    ],
                  },
                ]
              : [
                  {
                    title: <>{t("commissioning.for_all_veg_shares")}</>,
                    dataIndex: "for_all_harvest_shares",
                    key: "for_all_harvest_shares",
                    inputType: "checkbox",
                    required: false,
                    className: "column-group-start",
                  },
                ]),
            ...(shareTypeVariationsFruitsCount > 1
              ? [
                  {
                    title: (
                      <span className="text-xs">
                        {t("commissioning.for_fruit_shares")}
                      </span>
                    ),
                    key: "for_shares",
                    className: "column-group-start",
                    children: [
                      {
                        title: <>{t("commissioning.for_all")}</>,
                        dataIndex: "for_all_harvest_shares_fruit",
                        key: "for_all_harvest_shares_fruit",
                        inputType: "checkbox",
                        required: false,
                        className: "column-group-start",
                        onFieldChange: onForAllFruitChange,
                      },
                      ...shareVariationFruitsColumns,
                    ],
                  },
                ]
              : [
                  {
                    title: <>{t("commissioning.for_all_fruit_shares")}</>,
                    dataIndex: "for_all_harvest_shares_fruit",
                    key: "for_all_harvest_shares_fruit",
                    inputType: "checkbox",
                    required: false,
                    className: "column-group-start",
                  },
                ]),
          ]
        : [
            {
              title: (
                <span className="text-xs">{t("commissioning.for_shares")}</span>
              ),
              key: "for_shares",
              className: "column-group-start",
              children: [
                {
                  title: <>{t("commissioning.for_all")}</>,
                  dataIndex: "for_all_harvest_shares",
                  key: "for_all_harvest_shares",
                  inputType: "checkbox",
                  required: false,
                  className: "column-group-start",
                  onFieldChange: onForAllVegChange,
                },
                ...shareVariationColumns,
              ],
            },
          ]),
      ...(sells_to_resellers
        ? [
            ...(offerGroupsCount > 1
              ? [
                  {
                    title: (
                      <span className="text-xs">
                        {t("commissioning.for_resellers")}
                      </span>
                    ),
                    key: "for_resellers",
                    className: "column-group-start",
                    children: [
                      {
                        title: <>{t("commissioning.for_all")}</>,
                        dataIndex: "for_all_resellers",
                        key: "for_all_resellers",
                        inputType: "checkbox",
                        required: false,
                        className: "column-group-start",
                        disabled: isResellerDisabled,
                      },
                      ...offerGroupColumns,
                    ],
                  },
                ]
              : [
                  {
                    title: <>{t("commissioning.for_resellers")}</>,
                    dataIndex: "for_all_resellers",
                    key: "for_all_resellers",
                    inputType: "checkbox",
                    required: false,
                    className: "column-group-start",
                    disabled: isResellerDisabled,
                  },
                ]),
          ]
        : []),
      ...(has_markets
        ? [
            {
              title: <>{t("commissioning.for_all_markets")}</>,
              dataIndex: "for_all_markets",
              key: "for_all_markets",
              inputType: "checkbox",
              required: false,
              className: "column-group-start",
            },
          ]
        : []),
      ...(countPlots > 0
        ? [
            {
              title: <>{t("commissioning.plot")}</>,
              dataIndex: "plot_name",
              key: "plot_name",
              inputType: "select",
              options: plots,
              required: false,
              sortable: true,

              width: "14em",
              align: "center",
              className: "column-group-start",
              foreignKey: {
                valueField: "plot",
                displayField: "plot_name",
              },
            },
            {
              title: <>{t("commissioning.bed_number")}</>,
              dataIndex: "bed_number",
              key: "bed_number",
              inputType: "positive_integer",
              width: "7em",
              align: "center",
              required: false,
              sortable: true,
            },
          ]
        : []),

      {
        ...noteColumn,
        title: <>{t("commissioning.note_forecast")}</>,
        inputType: "optional",
        ...(countPlots === 0 && { className: "column-group-start" }),
      },
    ] as EditableColumnConfig<TableRecord>[];
  }, [
    isComponentReady,
    shareArticleColumn,
    amountUnitSizeColumns,
    fruit_and_veg_shares_are_separate,
    shareTypeVariationsCount,
    shareVariationColumns,
    shareTypeVariationsFruitsCount,
    shareVariationFruitsColumns,
    onForAllVegChange,
    onForAllFruitChange,
    sells_to_resellers,
    offerGroupsCount,
    offerGroupColumns,
    isResellerDisabled,
    has_markets,
    countPlots,
    plots,
    t,
    finalColumn,
    noteColumn,
  ]);
}
