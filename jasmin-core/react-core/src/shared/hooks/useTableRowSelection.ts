import { useCallback, useMemo, useState, type Key } from "react";
import type {
  RowSelectionConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";

/**
 * Checkbox row-selection state + config for an EditableTable.
 *
 * Pass `isRowDisabled` to grey out non-selectable rows — typically the
 * unsaved add-row (`record.key === -1`) and rows that are past / already
 * finalized. Omit it to allow selecting every row.
 *
 * Wire it up, renaming on destructure to match the page's JSX names:
 *
 * ```ts
 * const {
 *   selectedRowKeys,
 *   onSelectedRowsChange: handleRowSelectionChange,
 *   rowSelection: rowSelectionConfig,
 *   clearSelection,
 * } = useTableRowSelection((record) => record.key === -1 || isPast);
 * ```
 */
export function useTableRowSelection<T extends TableRecord = TableRecord>(
  isRowDisabled?: (record: T) => boolean,
): {
  selectedRowKeys: (string | number)[];
  setSelectedRowKeys: React.Dispatch<
    React.SetStateAction<(string | number)[]>
  >;
  onSelectedRowsChange: (keys: Key[]) => void;
  rowSelection: RowSelectionConfig<T>;
  clearSelection: () => void;
} {
  const [selectedRowKeys, setSelectedRowKeys] = useState<(string | number)[]>(
    [],
  );

  const onSelectedRowsChange = useCallback((keys: Key[]) => {
    setSelectedRowKeys(keys as (string | number)[]);
  }, []);

  const clearSelection = useCallback(() => setSelectedRowKeys([]), []);

  const rowSelection = useMemo<RowSelectionConfig<T>>(
    () => ({
      type: "checkbox",
      getCheckboxProps: (record: T) => ({
        disabled: isRowDisabled ? isRowDisabled(record) : false,
      }),
    }),
    [isRowDisabled],
  );

  return {
    selectedRowKeys,
    setSelectedRowKeys,
    onSelectedRowsChange,
    rowSelection,
    clearSelection,
  };
}
