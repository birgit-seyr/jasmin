import { useMemo } from "react";
import { useCommissioningMarketProductGroupsList } from "@shared/api/generated/commissioning/commissioning";
import type { MarketProductGroup } from "@shared/api/generated/models";
import { toOptions, type Option } from "@hooks/internal/toOptions";

export type MarketProductGroupOption = Option<MarketProductGroup>;

/** The active market product groups as select options. */
export const useMarketProductGroups = () => {
  const { data, isLoading } = useCommissioningMarketProductGroupsList({
    is_active: true,
  });

  // Memoized so the options keep one reference between renders, for the
  // column memos that list them as a dependency.
  const productGroups: MarketProductGroupOption[] = useMemo(
    () => toOptions(data, (group) => `${group.number} ${group.name}`),
    [data],
  );

  return { productGroups, loading: isLoading };
};
