import { useCallback, useMemo } from "react";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import type { ShareArticleOption } from "./useShareArticles";
import type { ShareTypeVariationOption } from "./useShareTypeVariations";
import type { DeliveryDay } from "./columns/useDeliveryDayColumns";
import {
  dayVariationKey,
  parseDayVariationKey,
  planningModeTier,
} from "./columns/columnKeys";

interface UsePlanningSummaryDataParams {
  shareDeliveryDays: DeliveryDay[];
  shareTypeVariations: ShareTypeVariationOption[];
  planningMode: string;
  data: TableRecord[];
  vegetables_and_fruits: ShareArticleOption[] | undefined;
  shareVariationAmounts: Record<string, unknown> | null;
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
  shareVariationAmountsSummary: Record<string, string>,
  planningMode: string,
): number {
  let total = 0;
  for (const variation of shareTypeVariations) {
    if (planningMode === "tours") {
      deliveryDay.used_tours?.forEach((tourNumber: number) => {
        const key = dayVariationKey({
          dayId: deliveryDay.id!,
          variationId: variation.id!,
          tour: tourNumber,
        });
        const count = Number(shareVariationAmountsSummary[key]) || 0;
        const perShare = Number(record[key]) || 0;
        total += count * perShare;
      });
    } else if (planningMode === "stations") {
      deliveryDay.delivery_stations?.forEach((station) => {
        const key = dayVariationKey({
          dayId: deliveryDay.id!,
          variationId: variation.id!,
          station: station.id,
        });
        const count = Number(shareVariationAmountsSummary[key]) || 0;
        const perShare = Number(record[key]) || 0;
        total += count * perShare;
      });
    } else {
      const key = dayVariationKey({
        dayId: deliveryDay.id!,
        variationId: variation.id!,
      });
      const count = Number(shareVariationAmountsSummary[key]) || 0;
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
  shareVariationAmounts,
}: UsePlanningSummaryDataParams) {
  const shareVariationAmountsSummary = useMemo(() => {
    if (!shareVariationAmounts) {
      return {};
    }

    const summary: Record<string, string> = {};

    shareDeliveryDays.forEach((deliveryDay) => {
      shareTypeVariations.forEach((variation: ShareTypeVariationOption) => {
        if (planningMode === "basic") {
          const key = dayVariationKey({
            dayId: deliveryDay.id!,
            variationId: variation.id!,
          });
          summary[key] = String(
            Math.round((shareVariationAmounts[key] as number) || 0),
          );
        } else if (planningMode === "tours") {
          deliveryDay.used_tours?.forEach((tourNumber: number) => {
            const key = dayVariationKey({
          dayId: deliveryDay.id!,
          variationId: variation.id!,
          tour: tourNumber,
        });
            summary[key] = String(
              Math.round((shareVariationAmounts[key] as number) || 0),
            );
          });
        } else if (planningMode === "stations") {
          deliveryDay.delivery_stations?.forEach((station) => {
            const key = dayVariationKey({
          dayId: deliveryDay.id!,
          variationId: variation.id!,
          station: station.id,
        });
            summary[key] = String(
              Math.round((shareVariationAmounts[key] as number) || 0),
            );
          });
        }
      });
    });

    return summary;
  }, [
    shareVariationAmounts,
    shareDeliveryDays,
    shareTypeVariations,
    planningMode,
  ]);

  const calculateDayVariationSums = useCallback(
    (tableData: TableRecord[]) => {
      const sums: Record<string, number> = {};
      const dayVariationKeys = new Set<string>();
      const activeTier = planningModeTier(planningMode);

      tableData.forEach((item) => {
        Object.keys(item).forEach((key) => {
          // Only unprefixed cells for the ACTIVE mode's tier. Parsing (instead
          // of substring scans) keeps the `prefix === ""` guard explicit:
          // planning rows also carry `backup_day_…_variation_…` fields (they
          // seed the BackupModal) which must NOT count toward these totals.
          const parsed = parseDayVariationKey(key);
          if (parsed?.prefix === "" && parsed.tier === activeTier) {
            dayVariationKeys.add(key);
          }
        });
      });

      dayVariationKeys.forEach((dayVariationKey) => {
        let sum = 0;

        tableData.forEach((item) => {
          const amount = parseFloat(String(item[dayVariationKey])) || 0;
          if (amount === 0) return;

          if (item.unit === "KG") {
            sum += amount;
          } else {
            const rowOverride = parseFloat(String(item.kg_per_piece)) || 0;
            let conversionFactor = rowOverride;

            if (!conversionFactor) {
              if (item.unit === "PCS") {
                if (item.size === "S")
                  conversionFactor = item.kg_per_piece_S as number;
                else if (item.size === "M")
                  conversionFactor = item.kg_per_piece_M as number;
                else if (item.size === "L")
                  conversionFactor = item.kg_per_piece_L as number;
              } else if (item.unit === "BUNCH") {
                if (item.size === "S")
                  conversionFactor = item.kg_per_bunch_S as number;
                else if (item.size === "M")
                  conversionFactor = item.kg_per_bunch_M as number;
                else if (item.size === "L")
                  conversionFactor = item.kg_per_bunch_L as number;
              }
            }

            if (conversionFactor) {
              sum += amount * conversionFactor;
            }
          }
        });

        sums[dayVariationKey] = sum;
      });

      return sums;
    },
    [planningMode],
  );

  const calculateDayVariationCounts = useCallback(
    (tableData: TableRecord[]) => {
      const totals: Record<string, number> = {};
      const dayVariationKeys = new Set<string>();
      const activeTier = planningModeTier(planningMode);

      const priceMap = new Map(
        vegetables_and_fruits?.map((article: ShareArticleOption) => [
          article.id,
          article,
        ]) || [],
      );

      tableData.forEach((item) => {
        Object.keys(item).forEach((key) => {
          // Only unprefixed cells for the ACTIVE mode's tier. Parsing (instead
          // of substring scans) keeps the `prefix === ""` guard explicit:
          // planning rows also carry `backup_day_…_variation_…` fields (they
          // seed the BackupModal) which must NOT count toward these totals.
          const parsed = parseDayVariationKey(key);
          if (parsed?.prefix === "" && parsed.tier === activeTier) {
            dayVariationKeys.add(key);
          }
        });
      });

      dayVariationKeys.forEach((dayVariationKey) => {
        let total = 0;

        tableData.forEach((item) => {
          const amount = parseFloat(String(item[dayVariationKey])) || 0;
          if (amount === 0) return;

          const rowPriceOverride = parseFloat(String(item.price_per_unit)) || 0;
          let price = rowPriceOverride;

          if (!price) {
            const shareArticle = priceMap.get(item.share_article as string);
            if (!shareArticle) return;

            if (item.unit === "KG") {
              price =
                parseFloat(
                  String(
                    (shareArticle as unknown as Record<string, unknown>)
                      .net_price_for_boxes_kg,
                  ),
                ) || 0;
            } else if (item.unit === "PCS") {
              price =
                parseFloat(
                  String(
                    (shareArticle as unknown as Record<string, unknown>)
                      .net_price_for_boxes_pieces,
                  ),
                ) || 0;
            } else if (item.unit === "BUNCH") {
              price =
                parseFloat(
                  String(
                    (shareArticle as unknown as Record<string, unknown>)
                      .net_price_for_boxes_bunch,
                  ),
                ) || 0;
            }
          }

          total += amount * price;
        });

        totals[dayVariationKey] = total;
      });

      return totals;
    },
    [planningMode, vegetables_and_fruits],
  );

  const dayVariationSums = useMemo(() => {
    return calculateDayVariationSums(data);
  }, [data, calculateDayVariationSums]);

  const dayVariationCounts = useMemo(() => {
    return calculateDayVariationCounts(data);
  }, [data, calculateDayVariationCounts]);

  const averageWeightSubData = useMemo(() => {
    const subData: Record<string, number> = {};
    shareDeliveryDays.forEach((deliveryDay) => {
      shareTypeVariations.forEach((variation: ShareTypeVariationOption) => {
        const avgWeight = parseFloat(
          String((variation as unknown as Record<string, unknown>).average_weight ?? ""),
        );
        if (!avgWeight) return;
        if (planningMode === "basic") {
          const key = dayVariationKey({
            dayId: deliveryDay.id!,
            variationId: variation.id!,
          });
          subData[key] = avgWeight;
        } else if (planningMode === "tours") {
          deliveryDay.used_tours?.forEach((tourNumber: number) => {
            const key = dayVariationKey({
          dayId: deliveryDay.id!,
          variationId: variation.id!,
          tour: tourNumber,
        });
            subData[key] = avgWeight;
          });
        } else if (planningMode === "stations") {
          deliveryDay.delivery_stations?.forEach((station) => {
            const key = dayVariationKey({
          dayId: deliveryDay.id!,
          variationId: variation.id!,
          station: station.id,
        });
            subData[key] = avgWeight;
          });
        }
      });
    });
    return subData;
  }, [shareDeliveryDays, shareTypeVariations, planningMode]);

  const priceSumArticlesSubData = useMemo(() => {
    const subData: Record<string, number> = {};
    shareDeliveryDays.forEach((deliveryDay) => {
      shareTypeVariations.forEach((variation: ShareTypeVariationOption) => {
        const priceSumArticles = parseFloat(
          String((variation as unknown as Record<string, unknown>).active_price_sum_articles ?? ""),
        );
        if (!priceSumArticles) return;
        if (planningMode === "basic") {
          const key = dayVariationKey({
            dayId: deliveryDay.id!,
            variationId: variation.id!,
          });
          subData[key] = priceSumArticles;
        } else if (planningMode === "tours") {
          deliveryDay.used_tours?.forEach((tourNumber: number) => {
            const key = dayVariationKey({
          dayId: deliveryDay.id!,
          variationId: variation.id!,
          tour: tourNumber,
        });
            subData[key] = priceSumArticles;
          });
        } else if (planningMode === "stations") {
          deliveryDay.delivery_stations?.forEach((station) => {
            const key = dayVariationKey({
          dayId: deliveryDay.id!,
          variationId: variation.id!,
          station: station.id,
        });
            subData[key] = priceSumArticles;
          });
        }
      });
    });
    return subData;
  }, [shareDeliveryDays, shareTypeVariations, planningMode]);

  const summaryColumns = useMemo(() => {
    const dayVariationKeys: string[] = [];

    shareDeliveryDays.forEach((deliveryDay) => {
      shareTypeVariations.forEach((variation: ShareTypeVariationOption) => {
        if (planningMode === "basic") {
          const key = dayVariationKey({
            dayId: deliveryDay.id!,
            variationId: variation.id!,
          });
          if (!key.includes("_tour_") && !key.includes("_station_")) {
            dayVariationKeys.push(key);
          }
        } else if (planningMode === "tours") {
          deliveryDay.used_tours?.forEach((tourNumber: number) => {
            const key = dayVariationKey({
          dayId: deliveryDay.id!,
          variationId: variation.id!,
          tour: tourNumber,
        });
            dayVariationKeys.push(key);
          });
        } else if (planningMode === "stations") {
          deliveryDay.delivery_stations?.forEach((station) => {
            const key = dayVariationKey({
          dayId: deliveryDay.id!,
          variationId: variation.id!,
          station: station.id,
        });
            dayVariationKeys.push(key);
          });
        }
      });
    });

    return dayVariationKeys;
  }, [shareDeliveryDays, shareTypeVariations, planningMode]);

  return {
    shareVariationAmountsSummary,
    dayVariationSums,
    dayVariationCounts,
    averageWeightSubData,
    priceSumArticlesSubData,
    summaryColumns,
  };
}
