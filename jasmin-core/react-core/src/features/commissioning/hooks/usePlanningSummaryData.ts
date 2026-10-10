import { useCallback, useMemo } from "react";
import type { TFunction } from "i18next";
import type {
  SummaryRow,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import {
  SUMMARY_ROW_STYLE,
  SUMMARY_ROW_STYLE_HIGHLIGHT,
} from "@shared/tables/summaryRowStyle";
import type { ShareArticleOption } from "./useShareArticles";
import type { ShareTypeVariationOption } from "./useShareTypeVariations";
import type { DeliveryDay } from "./columns/useDeliveryDayColumns";
import { kgPerRowUnit, pricePerRowUnit } from "../utils/planningRow";
import { dayCellKeys } from "./columns/columnKeys";

interface UsePlanningSummaryDataParams {
  shareDeliveryDays: DeliveryDay[];
  shareTypeVariations: ShareTypeVariationOption[];
  planningMode: string;
  data: TableRecord[];
  vegetables_and_fruits: ShareArticleOption[] | undefined;
  shareTypeVariationAmounts: Record<string, unknown> | null;
  // Passed in so the hook can assemble the ready-to-render ``summaryRows`` (kept
  // out of the page): translations, the currency suffix, and the historical
  // 2-year averages row's data.
  t: TFunction;
  currencySymbol: string;
  historicalAverages: Record<string, string | number> | null | undefined;
}

/**
 * Live total amount needed for a single delivery day on a single share-article row.
 *
 * Formula: Σ over variations of (subscribers in that variation × amount per subscriber).
 * Mirrors the backend's planned-amount calculation but runs against the
 * in-edit values from `Form.useWatch` (passed in as `record`), so the
 * display updates as the user types without waiting for save.
 *
 * Handles all three planning modes — basic / tours / stations — by
 * iterating the right subkey shape for each.
 */
export function computePlannedAmountForDay(
  record: Record<string, unknown>,
  deliveryDay: DeliveryDay,
  shareTypeVariations: ShareTypeVariationOption[],
  shareTypeVariationAmountsSummary: Record<string, string>,
  planningMode: string,
): number {
  let total = 0;
  for (const variation of shareTypeVariations) {
    for (const key of dayCellKeys(deliveryDay, variation.id!, planningMode)) {
      const count = Number(shareTypeVariationAmountsSummary[key]) || 0;
      const perShare = Number(record[key]) || 0;
      total += count * perShare;
    }
  }
  return total;
}

export function usePlanningSummaryData({
  shareDeliveryDays,
  shareTypeVariations,
  planningMode,
  data,
  vegetables_and_fruits,
  shareTypeVariationAmounts,
  t,
  currencySymbol,
  historicalAverages,
}: UsePlanningSummaryDataParams) {
  // The (day, variation) cells the active planning mode edits, in column
  // order, each with its variation — the cells every summary row fills.
  const activeCells = useMemo(
    () =>
      shareDeliveryDays.flatMap((deliveryDay) =>
        shareTypeVariations.flatMap((variation: ShareTypeVariationOption) =>
          dayCellKeys(deliveryDay, variation.id!, planningMode).map((key) => ({
            key,
            variation,
          })),
        ),
      ),
    [shareDeliveryDays, shareTypeVariations, planningMode],
  );

  const summaryColumns = useMemo(
    () => activeCells.map(({ key }) => key),
    [activeCells],
  );

  const shareTypeVariationAmountsSummary = useMemo(() => {
    if (!shareTypeVariationAmounts) {
      return {};
    }

    const summary: Record<string, string> = {};
    summaryColumns.forEach((key) => {
      summary[key] = String(
        Math.round((shareTypeVariationAmounts[key] as number) || 0),
      );
    });
    return summary;
  }, [shareTypeVariationAmounts, summaryColumns]);

  const calculateDayVariationSums = useCallback(
    (tableData: TableRecord[]) => {
      const sums: Record<string, number> = {};

      // Only the active mode's own cells that some row carries: a row also
      // carries the other tiers and the `backup_…` cells that seed the
      // BackupModal.
      summaryColumns.forEach((dayVariationKey) => {
        if (!tableData.some((item) => dayVariationKey in item)) return;
        let sum = 0;

        tableData.forEach((item) => {
          const amount = parseFloat(String(item[dayVariationKey])) || 0;
          if (amount === 0) return;
          sum += amount * kgPerRowUnit(item);
        });

        sums[dayVariationKey] = sum;
      });

      return sums;
    },
    [summaryColumns],
  );

  const calculateDayVariationCounts = useCallback(
    (tableData: TableRecord[]) => {
      const totals: Record<string, number> = {};

      const priceMap = new Map(
        vegetables_and_fruits?.map((article: ShareArticleOption) => [
          article.id,
          article,
        ]) || [],
      );

      // Only the active mode's own cells that some row carries: a row also
      // carries the other tiers and the `backup_…` cells that seed the
      // BackupModal.
      summaryColumns.forEach((dayVariationKey) => {
        if (!tableData.some((item) => dayVariationKey in item)) return;
        let total = 0;

        tableData.forEach((item) => {
          const amount = parseFloat(String(item[dayVariationKey])) || 0;
          if (amount === 0) return;

          const article =
            typeof item.share_article === "string"
              ? priceMap.get(item.share_article)
              : undefined;
          const price = pricePerRowUnit(item, article);

          total += amount * price;
        });

        totals[dayVariationKey] = total;
      });

      return totals;
    },
    [summaryColumns, vegetables_and_fruits],
  );

  const dayVariationSums = useMemo(() => {
    return calculateDayVariationSums(data);
  }, [data, calculateDayVariationSums]);

  const dayVariationCounts = useMemo(() => {
    return calculateDayVariationCounts(data);
  }, [data, calculateDayVariationCounts]);

  const averageWeightSubData = useMemo(() => {
    const subData: Record<string, number> = {};
    activeCells.forEach(({ key, variation }) => {
      const avgWeight = parseFloat(variation.average_weight ?? "");
      if (avgWeight) subData[key] = avgWeight;
    });
    return subData;
  }, [activeCells]);

  const priceSumArticlesSubData = useMemo(() => {
    const subData: Record<string, number> = {};
    activeCells.forEach(({ key, variation }) => {
      const priceSumArticles = parseFloat(
        variation.active_price_sum_articles ?? "",
      );
      if (priceSumArticles) subData[key] = priceSumArticles;
    });
    return subData;
  }, [activeCells]);


  // Ready-to-render summary rows — assembled here (not in the page) so the two
  // amount rows, the price row and the historical row share one definition and
  // one style source (SUMMARY_ROW_STYLE / _HIGHLIGHT). The page just gates them
  // behind its "show summary rows" toggle.
  const summaryRows = useMemo<SummaryRow[]>(
    () => [
      {
        columns: summaryColumns,
        label: t("commissioning.share_type_variation_amounts"),
        data: shareTypeVariationAmountsSummary,
        style: SUMMARY_ROW_STYLE,
      },
      {
        columns: summaryColumns,
        label: t("commissioning.summary_label_harvest_share_planning"),
        subLabel: t("commissioning.predetermined_value"),
        data: dayVariationSums,
        suffix: "kg",
        subData: averageWeightSubData,
        subSuffix: "kg",
        style: SUMMARY_ROW_STYLE,
      },
      {
        columns: summaryColumns,
        label: t("commissioning.second_summary_label_harvest_share_planning"),
        subLabel: t("commissioning.predetermined_value"),
        data: dayVariationCounts,
        suffix: currencySymbol,
        subData: priceSumArticlesSubData,
        subSuffix: currencySymbol,
        style: SUMMARY_ROW_STYLE,
      },
      {
        columns: summaryColumns,
        label: t("commissioning.historical_average_2y"),
        data: historicalAverages ?? {},
        suffix: "kg",
        style: SUMMARY_ROW_STYLE_HIGHLIGHT,
      },
    ],
    [
      summaryColumns,
      shareTypeVariationAmountsSummary,
      dayVariationSums,
      averageWeightSubData,
      dayVariationCounts,
      priceSumArticlesSubData,
      historicalAverages,
      currencySymbol,
      t,
    ],
  );

  return {
    shareTypeVariationAmountsSummary,
    dayVariationSums,
    dayVariationCounts,
    averageWeightSubData,
    priceSumArticlesSubData,
    summaryColumns,
    summaryRows,
  };
}
