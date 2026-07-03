import { useCommissioningOffersList } from "@shared/api/generated/commissioning/commissioning";
import type { Offer, CommissioningOffersListParams } from "@shared/api/generated/models";
import { useNumberFormat } from "@hooks/useNumberFormat";
import { useUnitOptions } from "@hooks/useUnitOptions";
import { toOptions, type Option } from "@hooks/internal/toOptions";

export type OfferOption = Option<Offer>;

export const useOfferOptions = (params: CommissioningOffersListParams) => {
  const { format } = useNumberFormat();
  // Route the unit through the shared label helper so a unit the enum allows
  // but the create-article Select doesn't offer (LB/OZ/L/G) degrades to the
  // raw unit code instead of rendering the literal i18n key.
  const { getUnitLabel } = useUnitOptions();

  const { data, isLoading, error, refetch } = useCommissioningOffersList(params, {
    query: { enabled: !!params.reseller || !!params.offer_group },
  });

  const offers: OfferOption[] = toOptions(
    data,
    (o) =>
      `${o.share_article_name} [${getUnitLabel(o.unit)}] - (${format(Number(o.amount_per_pu ?? 0), 0)} ${getUnitLabel(o.unit)}/VPE)`,
  );

  return {
    offers,
    offersCount: offers.length,
    loading: isLoading,
    error,
    refetch,
  };
};
