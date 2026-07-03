import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useIsMobile } from '@hooks/index';
import { useStorages } from '@features/commissioning/hooks';
import BaseEntitySelector, { type SelectorOption } from "@shared/selectors/BaseEntitySelector";

interface StorageSelectorProps {
  selectedStorage: string | null;
  setSelectedStorage: (value: string) => void;
  onStorageChange?: ((value: string) => void) | null;
  include_null_option?: boolean;
  preserveSelection?: boolean;
}

const StorageSelector = ({
  selectedStorage,
  setSelectedStorage,
  onStorageChange = null,
  include_null_option = false,
  preserveSelection = true,
}: StorageSelectorProps) => {
  const { t } = useTranslation();
  const { storages, loading } = useStorages();
  const isMobile = useIsMobile();

  const options = useMemo<SelectorOption<string>[]>(() => {
    const opts: SelectorOption<string>[] = [];
    if (include_null_option) opts.push({ value: "none", label: "-" });
    storages.forEach((storage) =>
      opts.push({
        value: storage.value,
        label: storage.label || t("commissioning.all_storages"),
      }),
    );
    return opts;
  }, [storages, include_null_option, t]);

  return (
    <BaseEntitySelector<string>
      value={selectedStorage}
      onValueChange={setSelectedStorage}
      onChange={onStorageChange}
      options={options}
      loading={loading}
      placeholder={t("placeholder.storage_selector")}
      style={
        isMobile
          ? { width: "100%" }
          : { width: "15em", marginLeft: "2em", marginRight: "2em" }
      }
      autoSelectFirst
      preserveSelection={preserveSelection}
    />
  );
};

export default StorageSelector;
