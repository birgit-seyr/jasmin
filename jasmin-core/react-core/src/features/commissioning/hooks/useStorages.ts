import { useMemo } from "react";
import { useCommissioningStoragesList } from "@shared/api/generated/commissioning/commissioning";
import type { Storage } from "@shared/api/generated/models";
import { toOptions, type Option } from "@hooks/internal/toOptions";

export type StorageOption = Option<Storage>;

export const useStorages = () => {
  const { data, isLoading, error, refetch } = useCommissioningStoragesList({
    is_active: true,
  });

  const storages: StorageOption[] = useMemo(() => toOptions(data, (s) => s.name), [data]);

  return {
    storages,
    storagesCount: storages.length,
    loading: isLoading,
    error,
    refetch,
  };
};
