import { useCommissioningUnconfirmedCoopSharesUnconfirmedCountRetrieve } from "@shared/api/generated/commissioning/commissioning";

/**
 * Count of CoopShares (Geschäftsanteile) still awaiting office confirmation
 * (unconfirmed, not rejected, not cancelled). Drives the pending-confirmation
 * badge in the Members sidebar. Mirrors {@link useUnconfirmedMembers}.
 */
export const useUnconfirmedCoopShares = () => {
  const { data, isLoading, error, refetch } =
    useCommissioningUnconfirmedCoopSharesUnconfirmedCountRetrieve();

  const countUnconfirmedCoopShares = data?.count ?? 0;

  return { countUnconfirmedCoopShares, loading: isLoading, error, refetch };
};
