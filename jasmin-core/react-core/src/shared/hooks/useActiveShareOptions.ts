import { useCommissioningShareOptionsActiveRetrieve } from "@shared/api/generated/commissioning/commissioning";
import type { ActiveShareOptions } from "@shared/api/generated/models";

export function useActiveShareOptions() {
  const { data, isLoading } = useCommissioningShareOptionsActiveRetrieve();

  return {
    activeShareOptions: (data ?? {}) as ActiveShareOptions,
    loading: isLoading,
  };
}
