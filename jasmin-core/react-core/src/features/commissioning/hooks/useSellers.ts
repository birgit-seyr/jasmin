import { useCommissioningResellersList } from "@shared/api/generated/commissioning/commissioning";
import type { Reseller, CommissioningResellersListParams } from "@shared/api/generated/models";
import { toOptions, type Option } from "@hooks/internal/toOptions";

export type SellerOption = Option<Reseller>;

/**
 * A seller's name wherever the app shows it: the company name, else the name
 * members see, else the contact's first and last name.
 */
export const sellerLabel = (
  seller: Pick<Reseller, "company_name" | "name_for_member_pages" | "first_name" | "last_name">,
): string =>
  seller.company_name ||
  seller.name_for_member_pages ||
  `${seller.first_name ?? ""} ${seller.last_name ?? ""}`.trim();

export const useSellers = (params: CommissioningResellersListParams = {}) => {
  const { data, isLoading, error, refetch } = useCommissioningResellersList({
    is_active_seller: true,
    is_seller: true,
    ...params,
  });

  const sellers: SellerOption[] = toOptions(data, sellerLabel);

  return {
    sellers,
    loading: isLoading,
    error,
    refetch,
  };
};
