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
    // Label falls back through the best available name: company name →
    // name_for_member_pages → the contact's first/last name.
    (s) =>
      s.company_name ||
      s.name_for_member_pages ||
      `${s.first_name ?? ""} ${s.last_name ?? ""}`.trim(),
  );

  return {
    sellers,
    loading: isLoading,
    error,
    refetch,
  };
};
