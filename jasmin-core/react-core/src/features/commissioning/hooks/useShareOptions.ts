import { useCommissioningShareOptionsList } from "@shared/api/generated/commissioning/commissioning";

export function useShareOptions() {
  const { data, isLoading } = useCommissioningShareOptionsList();

  return {
    shareOptions: data ?? [],
    loading: isLoading,
  };
}
