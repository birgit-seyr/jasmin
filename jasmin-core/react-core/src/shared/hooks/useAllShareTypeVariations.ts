import { useQueries, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";

import {
  commissioningShareTypeVariationsList,
  getCommissioningShareTypeVariationsListQueryKey,
  getCommissioningShareTypeVariationsListQueryOptions,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningShareTypeVariationsListParams,
  ShareTypeVariation,
} from "@shared/api/generated/models";
import { toOptions, type Option } from "./internal/toOptions";
import { useShareVariationSizeOptions } from "./useShareVariationSizeOptions";

// a list of all share_type_variations from all share_types
// used for select in abos

export type ShareTypeVariationOption = Option<ShareTypeVariation>;

interface ShareTypeRef {
  // Optional/nullable to match the generated models (orval marks ``id``
  // readonly-optional); rows without an id are skipped below.
  id?: string | null;
  [key: string]: unknown;
}

/**
 * Fetch the merged variation list across one or more share types,
 * deduped by id.
 *
 * Pre-2026-06 this was a hand-rolled ``useEffect`` + ``async for``
 * loop that fired requests serially, kept its own ``loading`` /
 * ``error`` state, and didn't cache anything. ``useQueries`` from
 * TanStack Query replaces all of that:
 *
 *   * Fires the per-shareType requests IN PARALLEL — share types
 *     with N items used to take N × roundtrip; now they take 1 ×
 *     roundtrip (whichever is slowest).
 *   * Caches each per-shareType list under its own queryKey, so
 *     two pages that show the same share types share results.
 *   * Cancels in-flight requests when ``shareTypes`` changes (e.g.
 *     a tenant-settings flip mid-render no longer triggers a stale
 *     state write).
 *
 * Public return shape kept identical to the old hook
 * (``shareTypeVariations`` / ``loading`` / ``error`` / ``refetch``)
 * so consumers in ``Abos.tsx`` and ``WaitingListAbos.tsx`` don't
 * need to change.
 */
export const useAllShareTypeVariations = (
  shareTypes: ShareTypeRef[] | undefined,
  baseParams: Omit<CommissioningShareTypeVariationsListParams, "share_type"> = {},
) => {
  const { getShareVariationSizeLabel } = useShareVariationSizeOptions();
  const queryClient = useQueryClient();

  // ``baseParams`` is part of every per-shareType queryKey, so a
  // re-renders that pass a NEW object reference with the SAME values
  // would otherwise spawn a fresh cache miss every time. Stringify
  // once per render and memoize the parsed form — cheap and gives us
  // structural equality for the queryKey.
  const baseParamsKey = JSON.stringify(baseParams);
  const stableBaseParams = useMemo(
    () => JSON.parse(baseParamsKey) as typeof baseParams,
    [baseParamsKey],
  );

  // Sorted id list keeps the query order stable across renders even
  // when the parent passes shareTypes in a different sequence. Rows
  // without an id can't be queried, so they are dropped here.
  const sortedShareTypeIds = useMemo(
    () =>
      (shareTypes ?? [])
        .map((shareType) => shareType.id)
        .filter((id): id is string => Boolean(id))
        .sort(),
    [shareTypes],
  );

  const queries = useQueries({
    queries: sortedShareTypeIds.map((id) =>
      getCommissioningShareTypeVariationsListQueryOptions({
        ...stableBaseParams,
        share_type: id,
      }),
    ),
  });

  const shareTypeVariations = useMemo<ShareTypeVariationOption[]>(() => {
    const all: ShareTypeVariationOption[] = [];
    for (const q of queries) {
      if (!q.data) continue;
      all.push(
        ...toOptions(
          q.data,
          (stv) =>
            `${stv.share_type_name} ${getShareVariationSizeLabel(stv.size ?? "")}`,
        ),
      );
    }
    // Dedupe by id — two share types can legitimately surface the
    // same variation (shared-size variations across share types).
    const seen = new Set<string | number>();
    const deduped = all.filter((variation) => {
      if (seen.has(variation.value)) return false;
      seen.add(variation.value);
      return true;
    });
    // Re-sort by ``sort_order`` so the global order matches the
    // office's intent — without this, the concatenation above
    // interleaves share types in their fetch order (which the
    // backend can't help with: it can only sort within a single
    // share_type query). Stable sort preserves the within-share-type
    // backend order as the tiebreaker, which is already
    // ``-valid_from, sort_order, size_order``. The ``?? 0`` keeps
    // unset sort orders at the top — matches the backend's
    // ``PositiveIntegerField(default=0)``.
    return deduped.sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
  }, [queries, getShareVariationSizeLabel]);

  const loading = queries.some((q) => q.isPending);
  const error = queries.find((q) => q.error)?.error ?? null;

  // Equivalent of the previous manual ``refetch``: invalidate every
  // per-shareType list and let TanStack re-pull them in parallel.
  // Returning a Promise mirrors the old async signature for any
  // caller that ``await``-ed it.
  const refetch = useCallback(async () => {
    await Promise.all(
      sortedShareTypeIds.map((id) =>
        queryClient.invalidateQueries({
          queryKey: getCommissioningShareTypeVariationsListQueryKey({
            ...stableBaseParams,
            share_type: id,
          }),
        }),
      ),
    );
  }, [queryClient, sortedShareTypeIds, stableBaseParams]);

  return {
    shareTypeVariations,
    loading,
    error,
    refetch,
  };
};

// Re-exported for callers that want the imperative single-shot
// helper (some pages still use it for one-off lookups outside the
// render lifecycle).
export { commissioningShareTypeVariationsList };
