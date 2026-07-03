import { useMemo } from 'react';
import { useCommissioningShareTypeVariationsTotalsRetrieve } from '@shared/api/generated/commissioning/commissioning';
import type {
  CommissioningShareTypeVariationsTotalsRetrieveParams,
  ShareTypeVariationTotalRow,
} from '@shared/api/generated/models';

// Get total quantities for share type variations filtered by year/week/day/tour/station

interface VariationTotal {
  id: string;
  name: string;
  size: string;
  totalQuantity: number;
  [key: string]: unknown;
}

type ExtendedParams = Partial<CommissioningShareTypeVariationsTotalsRetrieveParams> & {
  physical_share_type_variations?: boolean;
};

export const useShareTypeVariationsAmounts = (params: ExtendedParams = {}) => {
  const enabled = !!(params.delivery_week && params.year && params.delivery_day);

  const { data, isLoading, error, refetch } = useCommissioningShareTypeVariationsTotalsRetrieve(
    params as CommissioningShareTypeVariationsTotalsRetrieveParams,
    { query: { enabled } },
  );

  const variationsTotals: VariationTotal[] = useMemo(() => {
    if (!data?.variations) return [];
    return data.variations.map((variation: ShareTypeVariationTotalRow) => ({
      id: variation.share__share_type_variation_id as string,
      name: variation.share__share_type_variation__name as string,
      size: variation.share__share_type_variation__size as string,
      totalQuantity: (variation.total_quantity as number) ?? 0,
      ...variation,
    }));
  }, [data]);

  const grandTotal = useMemo(
    () => variationsTotals.reduce((sum, variation) => sum + (variation.totalQuantity || 0), 0),
    [variationsTotals],
  );

  return {
    variationsTotals,
    variationsTotalsCount: variationsTotals.length,
    grandTotal,
    loading: isLoading,
    error,
    refetch,
  };
};