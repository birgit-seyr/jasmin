import { useCommissioningResellersList } from "@shared/api/generated/commissioning/commissioning";
import type { Reseller, CommissioningResellersListParams } from "@shared/api/generated/models";
import { toOptions, type Option } from "@hooks/internal/toOptions";

export type SellerOption = Option<Reseller>;

export const useSellers = (params: CommissioningResellersListParams = {}) => {
  const { data, isLoading, error, refetch } = useCommissioningResellersList({
    is_active_seller: true,
    is_seller: true,
    ...params,
  });

  const sellers: SellerOption[] = toOptions(
    data,
    (s) =>
      `${s.company_name ?? ""}${s.first_name ? ` - ${s.first_name}` : ""}${s.last_name ? ` - ${s.last_name}` : ""}`,
  );

  return {
    sellers,
    loading: isLoading,
    error,
    refetch,
  };
};
