import type { ReactNode } from "react";
import { useMemo } from "react";

import type { CommissioningShareTypeVariationsListParams } from "@shared/api/generated/models";
import type {
  EditableColumnConfig,
  InputType,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import type { ShareTypeVariationOption } from "../useShareTypeVariations";
import { useShareTypeVariations } from "../useShareTypeVariations";
import { useNumberFormat } from "@hooks/useNumberFormat";
import { useShareTypeVariationSizeOptions } from "@hooks/useShareTypeVariationSizeOptions";
import { variationColumnKey } from "./columnKeys";

// Re-exported for existing importers (barrel + pages) — the canonical
// definition now lives in ./columnKeys alongside the day×variation helpers.
export { variationColumnKey };

export interface ShareTypeVariationGroup {
  share_type_id: string;
  share_type_name: string;
  variations: ShareTypeVariationOption[];
}

export interface UseShareTypeVariationColumnsConfig {
  /** Query params forwarded to `useShareTypeVariations` (e.g. `active_at_date`). */
  filters?: CommissioningShareTypeVariationsListParams | null;
  /** Cell render override. Defaults to printing the raw value or empty string. */
  renderCell?: (
    value: unknown,
    record: TableRecord,
    variation: ShareTypeVariationOption,
  ) => ReactNode;
  /** Column width per variation cell. Defaults to `"5em"`. */
  width?: string | number;
  /**
   * Make cells editable with this input type. Omit (default) for a read-only
   * display column — e.g. `DeliveryStationsDetails` just renders counts.
   */
  inputType?: InputType;
}

export interface UseShareTypeVariationColumnsResult {
  variationColumns: EditableColumnConfig<TableRecord>[];
  variations: ShareTypeVariationOption[];
  shareTypeGroups: ShareTypeVariationGroup[];
  loading: boolean;
}

/**
 * Build the parent-share-type → child-variation column tree shared by
 * `DeliveryStationsDetails` (read-only count cells) and
 * `DefaultShareArticlesInShare` (editable quantity cells).
 *
 * Visual rhythm via CSS classes (see `tables.css`):
 *   `‖ S | M | L ‖ S | M | L ‖ …`
 * - `column-group-start` (thick) on every share-type group AND its first child
 * - `column-variation-start` (thin) on the 2nd+ children inside a group
 */
export const useShareTypeVariationColumns = (
  config: UseShareTypeVariationColumnsConfig = {},
): UseShareTypeVariationColumnsResult => {
  const { filters, renderCell, width = "5em", inputType } = config;

  const { shareTypeVariations: variations, loading } = useShareTypeVariations(
    filters ?? {},
  );
  const { locale } = useNumberFormat();
  const { getShareTypeVariationSizeLabel } = useShareTypeVariationSizeOptions();

  const shareTypeGroups = useMemo<ShareTypeVariationGroup[]>(() => {
    const groups = new Map<string, ShareTypeVariationGroup>();
    for (const v of variations) {
      if (!v.share_type) continue;
      let group = groups.get(v.share_type);
      if (!group) {
        group = {
          share_type_id: v.share_type,
          share_type_name: v.share_type_name ?? "",
          variations: [],
        };
        groups.set(v.share_type, group);
      }
      group.variations.push(v);
    }
    const out = Array.from(groups.values());
    // Honour the per-variation ``sort_order`` the office sets (S/M/L as 1/2/3
    // renders S, M, L) — NOT an alphabetical size sort (which would give
    // L, M, S). Falls back to size only to break ties when sort_order is unset
    // (all default 0). Mirrors ``useAllShareTypeVariations``.
    out.forEach((g) =>
      g.variations.sort(
        (a, b) =>
          (a.sort_order ?? 0) - (b.sort_order ?? 0) ||
          (a.size ?? "").localeCompare(b.size ?? ""),
      ),
    );
    out.sort((a, b) =>
      (a.share_type_name ?? "").localeCompare(b.share_type_name ?? ""),
    );
    return out;
  }, [variations]);

  const variationColumns = useMemo<EditableColumnConfig<TableRecord>[]>(() => {
    // Trim trailing zeros AND honour the tenant's number_locale:
    // de-DE → "2,5", en-US → "2.5". Capped at 6 decimals so floating-point
    // noise doesn't leak through. Going via Intl.NumberFormat instead of
    // toString() is what swaps the decimal char per tenant.
    const trimFormatter = new Intl.NumberFormat(locale, {
      maximumFractionDigits: 6,
    });
    const defaultRender = (value: unknown) => {
      if (value === null || value === undefined || value === "") return "";
      const n = Number(value);
      if (!Number.isFinite(n)) return String(value);
      return trimFormatter.format(n);
    };

    return shareTypeGroups.map((group): EditableColumnConfig<TableRecord> => {
      const children: EditableColumnConfig<TableRecord>[] =
        group.variations.map((variation, childIdx) => ({
          title: (
            <span style={{ fontSize: "0.85em" }}>
              {getShareTypeVariationSizeLabel(variation.size)}
            </span>
          ),
          dataIndex: variationColumnKey(variation.id!),
          key: variationColumnKey(variation.id!),
          align: "center",
          width,
          ...(inputType ? { inputType, required: false } : {}),
          className:
            childIdx === 0 ? "column-group-start" : "column-variation-start",
          render: renderCell
            ? (value, record) =>
                renderCell(value, record as TableRecord, variation)
            : defaultRender,
        }));

      // Single-variation share types render as a flat column with a combined
      // title so the header isn't an awkward 1-child group.
      if (children.length === 1) {
        const onlyChild = children[0]!;
        const onlyVariation = group.variations[0];
        return {
          ...onlyChild,
          title: (
            <>
              {group.share_type_name}
              {onlyVariation?.size
                ? ` - ${getShareTypeVariationSizeLabel(onlyVariation.size)}`
                : ""}
            </>
          ),
          className: "column-group-start",
        };
      }

      return {
        title: <>{group.share_type_name}</>,
        dataIndex: `share_type_${group.share_type_id}`,
        key: `share_type_${group.share_type_id}`,
        align: "center",
        className: "column-group-start",
        children,
      };
    });
  }, [
    shareTypeGroups,
    renderCell,
    width,
    inputType,
    locale,
    getShareTypeVariationSizeLabel,
  ]);

  return { variationColumns, variations, shareTypeGroups, loading };
};
