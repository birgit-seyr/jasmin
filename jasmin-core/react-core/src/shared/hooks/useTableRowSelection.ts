import { useCallback, useMemo, useState, type Key } from "react";
import { useTranslation } from "react-i18next";
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
 * On a paginated table the header checkbox ticks the visible page only. Pass
 * the table's rows as `allRows` for a menu beside it that ticks every row of
 * every page that isn't disabled, or none. AntD's own "select all data" reads
 * the disabled flag of the visible page only, so it would tick a disabled row
 * on another page. The menu sets the page's selection, so the table has to
 * get `selectedRowKeys` from the page.
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
  { allRows }: { allRows?: T[] } = {},
): {
  selectedRowKeys: (string | number)[];
  setSelectedRowKeys: React.Dispatch<
    React.SetStateAction<(string | number)[]>
  >;
  onSelectedRowsChange: (keys: Key[]) => void;
  rowSelection: RowSelectionConfig<T>;
  clearSelection: () => void;
} {
  const { t } = useTranslation();
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
      ...(allRows && {
        selections: [
          {
            key: "all-pages",
            text: t("table.select_all_pages"),
            // The table keys its rows by id.
            onSelect: () =>
              setSelectedRowKeys(
                allRows
                  .filter((row) => !isRowDisabled?.(row))
                  .map((row) => (row.id ?? row.key) as string | number),
              ),
          },
          // AntD's own "clear" has no German text.
          {
            key: "none",
            text: t("table.select_none"),
            onSelect: () => setSelectedRowKeys([]),
          },
        ],
      }),
    }),
    [isRowDisabled, allRows, t],
  );

  return {
    selectedRowKeys,
    setSelectedRowKeys,
    onSelectedRowsChange,
    rowSelection,
    clearSelection,
  };
}
