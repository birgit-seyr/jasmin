import { useQueries } from "@tanstack/react-query";
import { useMemo } from "react";
import { getCommissioningShareTypeVariationsTotalsRetrieveQueryOptions } from "@shared/api/generated/commissioning/commissioning";
import type { CommissioningShareTypeVariationsTotalsRetrieveParams } from "@shared/api/generated/models";

export interface VariationsTotalEntry {
  id: string | number;
  size: string;
  totalQuantity: number;
}

export interface VariationsTotalsFilters {
  year?: number | null;
  delivery_week?: number | null;
  /** sharesdeliveryday ID, or an array of IDs to aggregate across. */
  delivery_day?: number | string | (number | string)[] | null;
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
 * day IDs (e.g. when one harvest day serves multiple delivery days);
 * issues one query per ID via ``useQueries`` and aggregates client-side.
 */
export function useAggregatedVariationsTotals(
  filters?: VariationsTotalsFilters,
): { entries: VariationsTotalEntry[]; loading: boolean } {
  const deliveryDayIds = useMemo<string[]>(() => {
    const raw = filters?.delivery_day;
    if (raw == null) return [];
    const arr = Array.isArray(raw) ? raw : [raw];
    return arr.filter((v) => v != null && v !== "").map((v) => String(v));
  }, [filters?.delivery_day]);

  const canFetch = !!(
    filters?.year &&
    filters?.delivery_week &&
    deliveryDayIds.length > 0
  );

  const queries = useQueries({
    queries: canFetch
      ? deliveryDayIds.map((dayId) => {
          const params: CommissioningShareTypeVariationsTotalsRetrieveParams = {
            year: filters!.year as number,
            delivery_week: filters!.delivery_week as number,
            delivery_day: dayId,
            ...(filters?.tour != null && { tour: Number(filters.tour) }),
            ...(filters?.delivery_station != null && {
              delivery_station: String(filters.delivery_station),
            }),
            ...(filters?.share_type != null && {
              share_type: String(filters.share_type),
            }),
            ...(filters?.physical_share_type_variations != null && {
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
      const variations = (
        q.data as { variations?: Record<string, unknown>[] } | undefined
      )?.variations;
      if (!variations) return;
      variations.forEach((v) => {
        const id = String(
          v.share__share_type_variation_id ??
            v.id ??
            v.share__share_type_variation__name,
        );
        const size = (v.share__share_type_variation__size as string) ?? "";
        const qty = (v.total_quantity as number) ?? 0;
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
