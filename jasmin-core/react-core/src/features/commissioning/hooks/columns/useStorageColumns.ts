import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import type {
  EditableColumnConfig,
  TableRecord,
} from '@shared/tables/BasicEditableTable/types';
import { useStorages } from '../useStorages';

interface StorageColumnOptions {
  onFieldChange?: EditableColumnConfig<TableRecord>["onFieldChange"];
  titleTemplate?: string;
  [key: string]: unknown;
}

export const useStorageColumns = (options: StorageColumnOptions = {}) => {
  const { t } = useTranslation();
  const { storages, storagesCount } = useStorages();
  const {
    onFieldChange,
    titleTemplate = "commissioning.in_storage",
    ...columnOverrides
  } = options;

  const storageIds = useMemo(() => storages.map((s) => s.id), [storages]);

  const defaultHandleStorageChange = useMemo<
    NonNullable<EditableColumnConfig<TableRecord>["onFieldChange"]>
  >(() => {
    return (storageValue, _record, _form, changedFieldName) => {
      if (storageValue === true) {
        const updates: Record<string, boolean> = {};
        storageIds.forEach((storageId) => {
          const fieldName = `storage_${storageId}`;
          if (fieldName !== changedFieldName) {
            updates[fieldName] = false;
          }
        });
        return updates;
      }
      return {};
    };
  }, [storageIds]);

  const storageColumns = useMemo<EditableColumnConfig<TableRecord>[]>(() => {
    return storages.map((storage) => ({
      title: t(titleTemplate, { storage_name: storage.name }),
      dataIndex: `storage_${storage.id}`,
      inputType: "checkbox",
      key: `storage${storage.id}`,
      align: "center",
      onFieldChange: onFieldChange ?? defaultHandleStorageChange,
      sortable: true,
      ...columnOverrides,
    }));
  }, [storages, t, titleTemplate, onFieldChange, defaultHandleStorageChange, columnOverrides]);

  return {
    storageColumns,
    storagesCount,
    storageIds,
    handleStorageChange: onFieldChange ?? defaultHandleStorageChange,
  };
};