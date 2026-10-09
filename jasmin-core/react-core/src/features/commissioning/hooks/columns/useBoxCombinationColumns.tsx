import type { ReactNode } from "react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { PackingBoxesMatrixColumn } from "@shared/api/generated/models";
import { ShareTypeVariationSizeEnum } from "@shared/api/generated/models";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { useNumberFormat } from "@hooks/index";

import BoxCombinationLabel from "../../components/BoxCombinationLabel";

// Sizes rank in their declared order (XS < S < M < L < …), as the backend's
// matrix sort does; an unknown size goes last.
const sizeRanks = new Map<string, number>(
  Object.values(ShareTypeVariationSizeEnum).map((size, index) => [size, index]),
);
const sizeRank = (size: string) => sizeRanks.get(size) ?? sizeRanks.size;

interface UseBoxCombinationColumnsOptions {
  /** Width of each combination (leaf) column. */
  width?: string;
  /** Cell renderer. Defaults to hide-zeros + integer format. */
  renderCell?: (value: unknown, record: TableRecord, index: number) => ReactNode;
}

/**
 * Builds the grouped combination columns shared by the packing boxes matrix
 * and the delivery-station member matrix: combination leaf columns (rendered
 * with `BoxCombinationLabel` — base size + add-on badges, honoring
 * `sort_order`) grouped under a parent header = the base share_type's
 * `short_name`. Leaves sort as the backend sorts them: sort order, size,
 * add-on count, key. Returns `EditableColumnConfig[]` (a superset of AntD's column
 * type, so an AntD `Table` consumer can cast).
 */
export function useBoxCombinationColumns(
  columns: PackingBoxesMatrixColumn[],
  options: UseBoxCombinationColumnsOptions = {},
): EditableColumnConfig<TableRecord>[] {
  const { t } = useTranslation();
  const { format } = useNumberFormat();
  const { width = "5em", renderCell } = options;

  return useMemo(() => {
    const cellRender =
      renderCell ??
      ((value: unknown) => {
        const n = Number(value);
        if (!Number.isFinite(n) || n === 0) return "";
        return format(n, 0);
      });

    const groups = new Map<
      string,
      { name: string; sort: number; cols: PackingBoxesMatrixColumn[] }
    >();
    for (const col of columns) {
      const groupId = col.base_share_type_id ?? "__none__";
      if (!groups.has(groupId)) {
        groups.set(groupId, {
          name: col.base_variation_id
            ? col.base_share_type_short_name
            : t("commissioning.no_base_combination"),
          sort: col.base_share_type_sort_index,
          cols: [],
        });
      }
      groups.get(groupId)!.cols.push(col);
    }

    return [...groups.entries()]
      .sort(([, a], [, b]) => a.sort - b.sort)
      .map(
        ([groupId, group]): EditableColumnConfig<TableRecord> => ({
          title: group.name,
          dataIndex: `group_${groupId}`,
          key: `group_${groupId}`,
          align: "center",
          children: group.cols
            .slice()
            .sort(
              (a, b) =>
                a.base_sort_order - b.base_sort_order ||
                sizeRank(a.base_size) - sizeRank(b.base_size) ||
                a.add_ons.length - b.add_ons.length ||
                a.key.localeCompare(b.key),
            )
            .map(
              (col): EditableColumnConfig<TableRecord> => ({
                title: (
                  <BoxCombinationLabel
                    baseSize={col.base_variation_id ? col.base_size : null}
                    addOns={col.add_ons}
                    noBaseLabel={t("commissioning.no_base_combination")}
                  />
                ),
                dataIndex: col.key,
                key: col.key,
                align: "center",
                width,
                render: cellRender,
              }),
            ),
        }),
      );
  }, [columns, t, format, width, renderCell]);
}
