import { useMemo } from "react";
import { useCommissioningOfferGroupsList } from "@shared/api/generated/commissioning/commissioning";
import type { OfferGroup } from "@shared/api/generated/models";
import { toOptions, type Option } from "@hooks/internal/toOptions";

export type OfferGroupOption = Option<OfferGroup>;

export const useOfferGroups = () => {
  const { data, isLoading, error, refetch } = useCommissioningOfferGroupsList();

  // Memoize so the derived array keeps a stable reference between renders
  // (``toOptions`` allocates a fresh array each call) — consumers that put
  // ``offerGroups`` in a useMemo/useEffect dep list rely on this.
  const offerGroups: OfferGroupOption[] = useMemo(
    () => toOptions(data, (og) => og.name ?? ""),
    [data],
  );

  // The protected default offer group (seeded per tenant) — the one
  // pre-selected for new resellers. Falls back to the lowest-numbered group
  // (the list is ordered by number) if the flag is somehow absent.
  const defaultOfferGroupId = useMemo(() => {
    if (!data || data.length === 0) return undefined;
    return (data.find((og) => og.is_default) ?? data[0]).id;
  }, [data]);

  return {
    offerGroups,
    offerGroupsCount: offerGroups.length,
    defaultOfferGroupId,
    loading: isLoading,
    error,
    refetch,
  };
};
