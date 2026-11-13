import type { TFunction } from "i18next";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useCommissioningMarketProductGroupsList } from "@shared/api/generated/commissioning/commissioning";
import type { MarketPrice } from "@shared/api/generated/models";
import { useCurrency } from "@hooks/configuration/useCurrency";
import { useUnitOptions } from "@hooks/useUnitOptions";
import type { MarketOrderListGroup } from "@features/commissioning/pdfs/exports/MarketOrderListPDF";
import { useMarketArticles } from "./useMarketArticles";

/** A product group's heading in the market lists, e.g. "4 Apples". The price
 *  list and the order list share it, so one choice of groups narrows both. */
export const marketProductGroupLabel = (
  number: number | null | undefined,
  name: string | null | undefined,
  t: TFunction,
) =>
  number == null
    ? t("commissioning.market_price_list_without_group")
    : `${number} ${name ?? ""}`;

/**
 * The market's order list for a week: every active PLU by product group (by
 * group number, then PLU, the PLUs without a group last), with the week's
 * price and origin where it has one. Null while anything is still loading.
 */
export const useMarketOrderListGroups = (
  prices: MarketPrice[] | undefined,
): MarketOrderListGroup[] | null => {
  const { t } = useTranslation();
  const { formatCurrency } = useCurrency();
  const { getUnitLabel } = useUnitOptions();
  const { marketArticles, loading: articlesLoading } = useMarketArticles();
  // Every group, the inactive ones too: an active PLU may still be filed
  // under a group switched off, and the price list names it all the same.
  const { data: productGroups, isLoading: groupsLoading } =
    useCommissioningMarketProductGroupsList();

  return useMemo(() => {
    if (!prices || !productGroups || articlesLoading || groupsLoading) return null;
    const groupById = new Map(productGroups.map((group) => [group.id, group]));
    const priceByArticle = new Map(
      prices.map((price) => [price.market_article, price]),
    );
    const byLabel = new Map<string, MarketOrderListGroup & { number: number }>();
    for (const plu of [...marketArticles].sort(
      (a, b) => a.plu_number - b.plu_number,
    )) {
      const group = plu.product_group ? groupById.get(plu.product_group) : null;
      const label = marketProductGroupLabel(group?.number, group?.name, t);
      const entry = byLabel.get(label) ?? {
        label,
        number: group?.number ?? Number.MAX_SAFE_INTEGER,
        rows: [],
      };
      const price = priceByArticle.get(plu.id);
      entry.rows.push({
        id: plu.id,
        plu_number: plu.plu_number,
        name: [plu.name, price?.origin].filter(Boolean).join(" "),
        unit_label: getUnitLabel(plu.unit),
        price_text: price ? formatCurrency(Number(price.gross_price)) : "",
      });
      byLabel.set(label, entry);
    }
    return [...byLabel.values()]
      .sort((a, b) => a.number - b.number)
      .map(({ label, rows }) => ({ label, rows }));
  }, [
    prices,
    articlesLoading,
    groupsLoading,
    productGroups,
    marketArticles,
    t,
    getUnitLabel,
    formatCurrency,
  ]);
};
