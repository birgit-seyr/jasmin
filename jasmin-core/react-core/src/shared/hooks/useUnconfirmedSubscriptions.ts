import { useCommissioningUnconfirmedSubscriptionsUnconfirmedCountRetrieve } from "@shared/api/generated/commissioning/commissioning";

export const useUnconfirmedSubscriptions = () => {
  const { data, isLoading, error, refetch } =
    useCommissioningUnconfirmedSubscriptionsUnconfirmedCountRetrieve();

  const countUnconfirmedSubscriptions = data?.count ?? 0;

  return { countUnconfirmedSubscriptions, loading: isLoading, error, refetch };
};
