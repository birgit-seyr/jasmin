import { useCommissioningShareArticlesList } from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningShareArticlesListParams,
  ShareArticle,
} from "@shared/api/generated/models";
import { toOptions, type Option } from "@hooks/internal/toOptions";

export type ShareArticleOption = Option<ShareArticle>;

interface UseShareArticlesParams extends CommissioningShareArticlesListParams {
  /**
   * When ``true``, the backend bypasses its default ``is_extra=False`` filter
   * and returns BOTH regular and extra share articles. Used by Orders /
   * DeliveryNote / Invoice flows.
   */
  include_extra?: boolean;
  /**
   * Explicit ``is_extra`` filter. Use ``true`` on management pages that should
   * only show extra articles (e.g. ``ListExtraArticles``).
   */
  is_extra?: boolean;
}

export const useShareArticles = (params: UseShareArticlesParams = {}) => {
  const source = useCommissioningShareArticlesList(
    params as CommissioningShareArticlesListParams,
  );

  const shareArticles: ShareArticleOption[] = toOptions(
    source.data,
    (sa) => sa.name ?? "",
  );

  return {
    shareArticles,
    loading: source.isLoading,
    error: source.error,
    refetch: source.refetch,
  };
};
