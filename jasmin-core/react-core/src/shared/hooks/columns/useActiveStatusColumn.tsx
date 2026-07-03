import { ClockCircleOutlined } from "@ant-design/icons";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import {
  createDateRangeStatusRenderer,
  createDateRangeStatusSorter,
} from "@shared/utils";

interface ActiveStatusColumnOptions {
  validFromField?: string;
  validUntilField?: string;
  width?: string;
  /**
   * When set, the status column becomes the table's initial (uncontrolled)
   * sort. Use ``"descend"`` for the future → active → inactive grouping.
   */
  defaultSortOrder?: "ascend" | "descend";
  /**
   * Ids of freshly-added rows to pin to the TOP regardless of sort direction.
   * Needed when the table both auto-sorts by status AND adds rows inline: the
   * column sort otherwise overrides EditableTable's data-order pin, so a just-
   * added row sorts into the middle. Pass the table's ``recentlyAddedIds`` set.
   */
  pinnedIds?: ReadonlySet<string>;
}

export const useActiveStatusColumn = (
  options: ActiveStatusColumnOptions = {},
) => {
  const { t } = useTranslation();

  const {
    validFromField = "valid_from",
    validUntilField = "valid_until",
    width = "3.5em",
    defaultSortOrder,
    pinnedIds,
  } = options;

  const activeStatusColumn = useMemo<EditableColumnConfig<TableRecord>>(() => {
    const baseSorter = createDateRangeStatusSorter(validFromField, validUntilField);
    const sorter =
      pinnedIds && pinnedIds.size > 0
        ? (
            a: TableRecord,
            b: TableRecord,
            sortOrder?: "ascend" | "descend",
          ) => {
            const aPinned = a.id != null && pinnedIds.has(String(a.id));
            const bPinned = b.id != null && pinnedIds.has(String(b.id));
            // Keep pinned rows on top whichever way the column is sorted (AntD
            // reverses the comparator for "descend").
            if (aPinned && !bPinned) return sortOrder === "descend" ? 1 : -1;
            if (!aPinned && bPinned) return sortOrder === "descend" ? -1 : 1;
            return baseSorter(a, b);
          }
        : baseSorter;
    return {
      title: (
        <>
          <ClockCircleOutlined />
        </>
      ),
      dataIndex: "is_active",
      key: "is_active",
      align: "center",
      readOnly: true,
      disabled: true,
      width: width,
      sorter,
      defaultSortOrder,
      showSorterTooltip: false,
      render: createDateRangeStatusRenderer(t, {
        validFromField,
        validUntilField,
      }),
    };
  }, [t, validFromField, validUntilField, width, defaultSortOrder, pinnedIds]);

  return activeStatusColumn;
};
