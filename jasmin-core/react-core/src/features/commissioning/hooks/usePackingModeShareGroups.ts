import dayjs from "dayjs";
import { useMemo } from "react";
import { useAllShareTypeVariations } from "@hooks/useAllShareTypeVariations";
import { useShareTypes } from "@hooks/useShareTypes";

export interface PackingModeShareGroups {
  /** share_type ids that have ≥1 variation packed in BULK. */
  bulkShareTypeIds: Set<string>;
  /** share_type ids that have ≥1 variation packed in BOXES (not bulk). */
  boxesShareTypeIds: Set<string>;
  /** share_options that have ≥1 BULK-packed variation. */
  bulkShareOptions: Set<string>;
  /** share_options that have ≥1 BOXES (non-bulk) variation. */
  boxesShareOptions: Set<string>;
  loading: boolean;
}

/**
 * Groups the active share types / share options by whether they have at least
 * one variation packed in bulk vs. in boxes
 * (``ShareTypeVariation.is_packed_bulk``).
 *
 * Single source for the packing pages' scoping:
 *   * PackingListBulk  → only bulk-packed share types in its selector.
 *   * PackingListBoxes → only boxed share types in its selector.
 *   * CommissioningListPacking → a table per bulk-packed share option.
 *
 * Both underlying queries (share types + variations) go through TanStack
 * Query, so calling this hook alongside an existing ``useShareTypes`` with the
 * same ``activeAtDate`` reuses the cached result rather than re-fetching.
 */
export const usePackingModeShareGroups = (
  activeAtDate: string | undefined = undefined,
): PackingModeShareGroups => {
  const date = activeAtDate ?? dayjs().format("YYYY-MM-DD");
  const { shareTypes, loading: shareTypesLoading } = useShareTypes({
    active_at_date: date,
  });
  // Cast-free bridge: assigning to an object-literal type gives the array an
  // implicit index signature, satisfying the shared hook's ShareTypeRef.
  const shareTypeRefs: { id?: string | null }[] = shareTypes;
  const { shareTypeVariations, loading: variationsLoading } =
    useAllShareTypeVariations(shareTypeRefs, { active_at_date: date });

  return useMemo(() => {
    const optionByShareType = new Map<string, string | null | undefined>();
    for (const shareType of shareTypes) {
      if (!shareType.id) continue;
      optionByShareType.set(
        shareType.id,
        (shareType as { share_option?: string | null }).share_option,
      );
    }

    const bulkShareTypeIds = new Set<string>();
    const boxesShareTypeIds = new Set<string>();
    const bulkShareOptions = new Set<string>();
    const boxesShareOptions = new Set<string>();

    for (const variation of shareTypeVariations) {
      const shareTypeId = variation.share_type;
      if (!shareTypeId) continue;
      const option = optionByShareType.get(shareTypeId);
      if (variation.is_packed_bulk) {
        bulkShareTypeIds.add(shareTypeId);
        if (option) bulkShareOptions.add(option);
      } else {
        boxesShareTypeIds.add(shareTypeId);
        if (option) boxesShareOptions.add(option);
      }
    }

    return {
      bulkShareTypeIds,
      boxesShareTypeIds,
      bulkShareOptions,
      boxesShareOptions,
      loading: shareTypesLoading || variationsLoading,
    };
  }, [shareTypes, shareTypeVariations, shareTypesLoading, variationsLoading]);
};
