import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useShareArticles } from '@features/commissioning/hooks';
import BaseEntitySelector, { type SelectorOption } from "@shared/selectors/BaseEntitySelector";

interface ShareArticleSelectorProps {
  selectedShareArticle: string | null | undefined;
  setSelectedShareArticle: (value: string | null) => void;
  onShareArticleChange?: ((value: string | null) => void) | null;
  include_null_option?: boolean;
  preserveSelection?: boolean;
  additionalFilters?: Record<string, unknown>;
}

const ShareArticleSelector = ({
  selectedShareArticle,
  setSelectedShareArticle,
  onShareArticleChange = null,
  include_null_option = false,
  additionalFilters = {},
}: ShareArticleSelectorProps) => {
  const { t } = useTranslation();

  const params = useMemo(() => ({ ...additionalFilters }), [additionalFilters]);
  const { shareArticles, loading } = useShareArticles(
    params as Parameters<typeof useShareArticles>[0],
  );

  const options = useMemo<SelectorOption<string | null>[]>(() => {
    const opts: SelectorOption<string | null>[] = [];
    if (include_null_option) {
      opts.push({ value: null, label: t("commissioning.all_share_articles") });
    }
    shareArticles.forEach((sa) =>
      opts.push({ value: sa.value, label: sa.label }),
    );
    return opts;
  }, [shareArticles, include_null_option, t]);

  return (
    <BaseEntitySelector<string | null>
      value={selectedShareArticle ?? null}
      onValueChange={setSelectedShareArticle}
      onChange={onShareArticleChange}
      options={options}
      loading={loading}
      placeholder={t("placeholder.share_article_selector")}
      style={{ width: "22em" }}
      showSearch
    />
  );
};

export default ShareArticleSelector;
