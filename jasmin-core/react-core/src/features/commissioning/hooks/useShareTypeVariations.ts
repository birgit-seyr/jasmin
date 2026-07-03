import { useCommissioningShareTypeVariationsList } from "@shared/api/generated/commissioning/commissioning";
import type { ShareTypeVariation, CommissioningShareTypeVariationsListParams } from "@shared/api/generated/models";
import { toOptions, type Option } from "@hooks/internal/toOptions";

export type ShareTypeVariationOption = Option<ShareTypeVariation>;

export const useShareTypeVariations = (params: CommissioningShareTypeVariationsListParams | null = {}) => {
  const { data, isLoading, error, refetch } = useCommissioningShareTypeVariationsList(
    params ?? {},
    { query: { enabled: params !== null } },
  );

  const shareTypeVariations: ShareTypeVariationOption[] = toOptions(data, (stv) => stv.size!);

  return {
    shareTypeVariations,
    shareTypeVariationsCount: shareTypeVariations.length,
    loading: isLoading,
    error,
    refetch,
  };
};
