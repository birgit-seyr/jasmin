import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useCurrency } from "@hooks/index";
import { useOfferTiers } from "@features/commissioning/hooks";
import type { PriceColumn } from "./ExportCsvAtDateModal";

/**
 * The 13 price/tax columns for a CSV export of share-article pricing,
 * in the same order and with the same i18n labels the standalone
 * ``ExportCsvPricesShareArticle`` modal uses — `Bezeichnung,USt.,€/kg,
 * €/Stk.,€/Bund,€/kg ab N VPE,…`.
 *
 * The combined "all articles + crates" export reuses this so the price
 * portion of its CSV stays in lockstep with the single-purpose export.
 *
 * The order is: tax_rate, then 3 box prices (kg / pieces / bunch), then
 * N×3 reseller prices (kg / pieces / bunch × N configured tiers). The
 * reseller tier numbers come from the tenant setting
 * ``used_tiers_for_offers``. **No silent default to ``[1, 3, 5]``** —
 * if the tenant hasn't configured tiers, only the single ``price_1``
 * column per unit is emitted (single-tier mode).
 *
 * Callers prepend their own name column (the data key for the row's
 * display name differs: standalone price export uses `share_article_name`,
 * the combined export uses `name`).
 */
export function useSharePriceCsvColumns(): PriceColumn[] {
  const { t } = useTranslation();
  const { currencySymbol } = useCurrency();
  const tiersList = useOfferTiers();

  return useMemo(() => {
    const units: Array<"kg" | "pieces" | "bunch"> = ["kg", "pieces", "bunch"];
    const tiers: Array<{ tier: number; idx: 1 | 2 | 3 }> = tiersList.map(
      (tier, i) => ({ tier, idx: (i + 1) as 1 | 2 | 3 }),
    );
    const cols: PriceColumn[] = [
      { key: "tax_rate", label: t("commissioning.tax_rate") },
    ];
    for (const unit of units) {
      cols.push({
        key: `net_price_for_boxes_${unit}`,
        label: t(`commissioning.box_price_${unit}`, { currencySymbol }),
      });
    }
    for (const unit of units) {
      for (const { tier, idx } of tiers) {
        cols.push({
          key: `net_price_for_orders_${unit}_${idx}`,
          label: t(`commissioning.reseller_${unit}_tier${idx}`, {
            tier,
            currencySymbol,
          }),
        });
      }
    }
    return cols;
  }, [t, currencySymbol, tiersList]);
}
