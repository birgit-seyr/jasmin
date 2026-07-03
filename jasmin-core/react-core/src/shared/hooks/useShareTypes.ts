import { useMemo } from "react";
import { useCommissioningShareTypesList } from "@shared/api/generated/commissioning/commissioning";
import { ShareTypeEnum } from "@shared/api/generated/models";
import type { ShareType, CommissioningShareTypesListParams } from "@shared/api/generated/models";
import { toOptions, type Option } from "./internal/toOptions";

export type ShareTypeOption = Option<ShareType>;

// Canonical share-option order — the declaration order of the backend
// ShareOptions enum, kept in sync automatically via generate-api.
const SHARE_OPTION_ORDER = Object.values(ShareTypeEnum) as string[];

export const useShareTypes = (params: CommissioningShareTypesListParams = {}) => {
  const { data, isLoading, error, refetch } = useCommissioningShareTypesList(params);

  const shareTypes: ShareTypeOption[] = useMemo(() => {
    const rank = (option: ShareTypeOption) => {
      const index = SHARE_OPTION_ORDER.indexOf(option.share_option ?? "");
      return index === -1 ? SHARE_OPTION_ORDER.length : index;
    };
    // Stable sort by share_option order; within an option the backend's
    // -valid_from order is preserved.
    return [...toOptions(data, (st) => st.name ?? "")].sort(
      (a, b) => rank(a) - rank(b),
    );
  }, [data]);

  return {
    shareTypes,
    shareTypesCount: shareTypes.length,
    loading: isLoading,
    error,
    refetch,
  };
};
