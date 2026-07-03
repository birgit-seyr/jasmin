import { useCommissioningStoragesList } from "@shared/api/generated/commissioning/commissioning";
import type { Storage } from "@shared/api/generated/models";
import { toOptions, type Option } from "@hooks/internal/toOptions";

export type StorageOption = Option<Storage>;

export const useStorages = () => {
  const { data, isLoading, error, refetch } = useCommissioningStoragesList({
    is_active: true,
  });

  const storages: StorageOption[] = toOptions(data, (s) => s.name);

  return {
    storages,
    storagesCount: storages.length,
    loading: isLoading,
    error,
    refetch,
  };
};
