import { useCommissioningHistoricalShareTypeVariationAveragesRetrieve } from '@shared/api/generated/commissioning/commissioning';

interface HistoricalAverageParams {
  year?: number;
  delivery_week?: number;
  /** Explicit list of variation IDs. Either this OR `share_option` must be set. */
  share_type_variation_ids?: string[];
  /**
   * Resolve variation IDs server-side from a `share_option` (e.g. "gemuese").
   * Prefer this over `share_type_variation_ids` on pages where the same
   * `share_option` already drives a sibling /share-type-variations/ call —
   * the backend resolves both queries against the same filter shape, so
   * passing `share_option` here lets both requests fire in parallel instead
   * of forcing the historical-averages call to wait for the variations list.
   */
  share_option?: string;
  /** When using `share_option`: only consider variations active at this date. */
  active_at_date?: string;
  years_back?: number;
  /**
   * External gate, ANDed with the internal enablement. Pass `false` to skip
   * the request entirely (e.g. when the page has no share-type variations, so
   * the backend would 400 with "No matching share-type-variations"). Defaults
   * to `true`, so existing callers are unaffected.
   */
  enabled?: boolean;
}

export const useHistoricalShareTypeVariationAverages = (
  params: HistoricalAverageParams,
) => {
  const enabledByIds =
    !!params.share_type_variation_ids && params.share_type_variation_ids.length > 0;
  const enabledByOption = !!params.share_option;
  const enabled = !!(
    (params.enabled ?? true) &&
    params.year &&
    params.delivery_week &&
    (enabledByIds || enabledByOption)
  );

  const { data, isLoading, error } =
    useCommissioningHistoricalShareTypeVariationAveragesRetrieve(
      {
        year: params.year!,
        delivery_week: params.delivery_week!,
        // Orval-generated client typings expect this key; passing empty
        // strings is fine when share_option is set instead.
        share_type_variation_ids:
          params.share_type_variation_ids?.join(',') ?? '',
        ...(params.share_option && { share_option: params.share_option }),
        ...(params.active_at_date && { active_at_date: params.active_at_date }),
        years_back: params.years_back ?? 2,
      } as Parameters<typeof useCommissioningHistoricalShareTypeVariationAveragesRetrieve>[0],
      { query: { enabled } },
    );

  return { data: data ?? null, loading: isLoading, error };
};
