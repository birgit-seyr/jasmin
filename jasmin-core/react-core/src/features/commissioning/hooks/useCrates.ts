import { useMemo } from "react";
import { useCommissioningCratesList } from "@shared/api/generated/commissioning/commissioning";
import type { Crate, CommissioningCratesListParams } from "@shared/api/generated/models";
import { toOptions, toOptionsWithNull, type NullableOption } from "@hooks/internal/toOptions";

export type CrateOption = NullableOption<Crate>;

interface UseCratesParams extends CommissioningCratesListParams {
  includeNullOption?: boolean;
}

export const useCrates = (params: UseCratesParams = {}) => {
  const { includeNullOption = true, ...apiParams } = params;

  const { data, isLoading, error, refetch } = useCommissioningCratesList({
    is_active: true,
    ...apiParams,
  });

  // Memoize so the derived array keeps a stable reference between renders
  // (``toOptions``/``toOptionsWithNull`` allocate a fresh array each call) —
  // consumers that put ``crates`` in a useMemo/useEffect dep list rely on it.
  const crates: CrateOption[] = useMemo(() => {
    const toLabel = (c: Crate) => c.short_name || c.name;
    return includeNullOption
      ? toOptionsWithNull(data, toLabel)
      : toOptions(data, toLabel);
  }, [data, includeNullOption]);

  return {
    crates,
    loading: isLoading,
    error,
    refetch,
  };
};
