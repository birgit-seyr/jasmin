import { useMemo } from "react";
import { useCommissioningMarketArticlesList } from "@shared/api/generated/commissioning/commissioning";
import type { MarketArticle } from "@shared/api/generated/models";
import { toOptions, type Option } from "@hooks/internal/toOptions";

export type MarketArticleOption = Option<MarketArticle>;

/** The active PLUs as select options, labelled "PLU number name". */
export const useMarketArticles = () => {
  const { data, isLoading } = useCommissioningMarketArticlesList({
    is_active: true,
  });

  // Memoized so the options keep one reference between renders, for the
  // column memos that list them as a dependency.
  const marketArticles: MarketArticleOption[] = useMemo(
    () => toOptions(data, (plu) => `${plu.plu_number} ${plu.name}`),
    [data],
  );

  return { marketArticles, loading: isLoading };
};
