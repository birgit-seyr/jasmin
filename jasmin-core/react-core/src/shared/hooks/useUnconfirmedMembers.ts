import { useCommissioningUnconfirmedMembersUnconfirmedCountRetrieve } from "@shared/api/generated/commissioning/commissioning";

export const useUnconfirmedMembers = () => {
  const { data, isLoading, error, refetch } =
    useCommissioningUnconfirmedMembersUnconfirmedCountRetrieve();

  const countUnconfirmedMembers = data?.count ?? 0;

  return { countUnconfirmedMembers, loading: isLoading, error, refetch };
};
