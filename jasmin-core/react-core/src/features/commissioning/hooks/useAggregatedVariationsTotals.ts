import { useQueries } from "@tanstack/react-query";
import { useMemo } from "react";
import { getCommissioningShareTypeVariationsTotalsRetrieveQueryOptions } from "@shared/api/generated/commissioning/commissioning";
import type { CommissioningShareTypeVariationsTotalsRetrieveParams } from "@shared/api/generated/models";

export interface VariationsTotalEntry {
  id: string | number;
  size: string;
  totalQuantity: number;
}

/**
 * A delivery day in a week other than the filters' own — a harvest on Saturday
 * serves Monday's delivery of the next week.
 */
export interface VariationsTotalsDeliveryDay {
  id: number | string;
  year: number;
  delivery_week: number;
}

export interface VariationsTotalsFilters {
  year?: number | null;
  delivery_week?: number | null;
  /**
   * sharesdeliveryday ID, or an array of them to aggregate across. An array
   * entry may carry its own year and week, which then replace the filters'.
   */
  delivery_day?:
    | number
    | string
    | (number | string | VariationsTotalsDeliveryDay)[]
    | null;
  tour?: number | string | null;
  delivery_station?: number | string | null;
  share_type?: number | string | null;
  sending_share_type_id?: boolean;
  physical_share_type_variations?: boolean;
}

/**
 * Fetch share-type-variation totals for one or more delivery days and
 * sum them per variation id. Used by ``VariationsTotalsCard`` for the
 * on-screen summary, and by the HarvestingList PDF generator for the
 * same card on the first PDF page — so both display identical numbers.
 *
 * Accepts ``delivery_day`` either as a scalar (single day) or an array of
 * day IDs (e.g. when one harvest day serves multiple delivery days), each
 * optionally in a week of its own; issues one query per day via
 * ``useQueries`` and aggregates client-side.
 */
export function useAggregatedVariationsTotals(
  filters?: VariationsTotalsFilters,
): { entries: VariationsTotalEntry[]; loading: boolean } {
  const deliveryDays = useMemo(() => {
    const raw = filters?.delivery_day;
    if (raw == null) return [];
    const arr = Array.isArray(raw) ? raw : [raw];
    return arr.map((day) =>
      typeof day === "object"
        ? { id: String(day.id), year: day.year, week: day.delivery_week }
        : { id: String(day), year: filters?.year, week: filters?.delivery_week },
    );
  }, [filters?.delivery_day, filters?.year, filters?.delivery_week]);

  const canFetch =
    !!filters &&
    deliveryDays.length > 0 &&
    deliveryDays.every((day) => day.year && day.week);

  const queries = useQueries({
    queries: canFetch
      ? deliveryDays.map((day) => {
          const params: CommissioningShareTypeVariationsTotalsRetrieveParams = {
            year: day.year as number,
            delivery_week: day.week as number,
            delivery_day: day.id,
            ...(filters.tour != null && { tour: Number(filters.tour) }),
            ...(filters.delivery_station != null && {
              delivery_station: String(filters.delivery_station),
            }),
            ...(filters.share_type != null && {
              share_type: String(filters.share_type),
            }),
            ...(filters.physical_share_type_variations != null && {
              physical_share_type_variations:
                filters.physical_share_type_variations,
            }),
          };
          return getCommissioningShareTypeVariationsTotalsRetrieveQueryOptions(
            params,
          );
        })
      : [],
  });

  const entries = useMemo<VariationsTotalEntry[]>(() => {
    const byId = new Map<string, VariationsTotalEntry>();
    queries.forEach((q) => {
      const variations = q.data?.variations;
      if (!variations) return;
      variations.forEach((v) => {
        const id = v.share__share_type_variation_id;
        const size = v.share__share_type_variation__size;
        const qty = v.total_quantity;
        const existing = byId.get(id);
        if (existing) {
          existing.totalQuantity += qty;
        } else {
          byId.set(id, { id, size, totalQuantity: qty });
        }
      });
    });
    return Array.from(byId.values());
  }, [queries]);

  const loading = queries.some((q) => q.isLoading);

  return { entries, loading };
}
