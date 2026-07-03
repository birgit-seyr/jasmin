import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type {
  EditableColumnConfig,
  SelectOption,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { useSellers } from "../useSellers";

// Stable reference for the no-overrides case so the inner useMemo isn't
// invalidated on every render (see useIsActiveColumn for the same guard).
const EMPTY_OVERRIDES: Partial<EditableColumnConfig<TableRecord>> = {};

interface UseSellerColumnOptions {
  /** i18n key for the column title. Defaults to "commissioning.seller". */
  titleKey?: string;
  /** Extra column props merged last (align, sortable, width overrides, …). */
  overrides?: Partial<EditableColumnConfig<TableRecord>>;
}

/**
 * The "seller" select column shared by the harvest-planning grid, the purchase
 * documentation page and the default-share-content editor. Writes the seller id
 * to `seller` and displays `seller_name` (the row's derived label). Sellers are
 * loaded internally via useSellers, so callers only tweak title/overrides.
 */
export const useSellerColumn = ({
  titleKey = "commissioning.seller",
  overrides = EMPTY_OVERRIDES,
}: UseSellerColumnOptions = {}): EditableColumnConfig<TableRecord> => {
  const { t } = useTranslation();
  const { sellers } = useSellers();

  return useMemo(() => {
    const sellerOptions = sellers as SelectOption[];
    return {
      title: <>{t(titleKey)}</>,
      dataIndex: "seller_name",
      key: "seller_name",
      inputType: "select",
      // Not required → EditableTable's FormInput auto-prepends a blank "clear"
      // option, so the seller can be reset to none without a per-column flag.
      required: false,
      width: "16em",
      options: sellerOptions,
      foreignKey: {
        valueField: "seller",
        displayField: "seller_name",
      },
      ...overrides,
    };
  }, [t, titleKey, sellers, overrides]);
};
