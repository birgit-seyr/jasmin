import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useIsMobile } from '@hooks/index';
import { useStorages } from '@features/commissioning/hooks';
import BaseEntitySelector, { type SelectorOption } from "@shared/selectors/BaseEntitySelector";

interface StorageSelectorProps {
  selectedStorage: string | null;
  /** Gets `null` once the list loads empty, so no stale storage stays picked. */
  setSelectedStorage: (value: string | null) => void;
  onStorageChange?: ((value: string | null) => void) | null;
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

  const options = useMemo<SelectorOption<string | null>[]>(() => {
    const opts: SelectorOption<string | null>[] = [];
    if (include_null_option) opts.push({ value: "none", label: "-" });
    storages.forEach((storage) =>
      opts.push({
        value: storage.value,
        label: storage.label,
      }),
    );
    return opts;
  }, [storages, include_null_option]);

  return (
    <BaseEntitySelector<string | null>
      value={selectedStorage}
      onValueChange={setSelectedStorage}
      onChange={onStorageChange}
      options={options}
      loading={loading}
      placeholder={t("placeholder.storage_selector")}
      className={`bold-select week-selector-select ${
        isMobile ? "w-full" : "storage-selector"
      }`}
      autoSelectFirst
      preserveSelection={preserveSelection}
      emptyValue={null}
    />
  );
};

export default StorageSelector;
