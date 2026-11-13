import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useMarketProductGroups } from "@features/commissioning/hooks";
import BaseEntitySelector, {
  type SelectorOption,
} from "@shared/selectors/BaseEntitySelector";

interface MarketProductGroupSelectorProps {
  /** The picked group's id, or `null` for all of them. */
  selectedProductGroup: string | null;
  setSelectedProductGroup: (value: string | null) => void;
}

/** One active market product group, or all of them; a pick that is switched
 *  off goes back to all. */
const MarketProductGroupSelector = ({
  selectedProductGroup,
  setSelectedProductGroup,
}: MarketProductGroupSelectorProps) => {
  const { t } = useTranslation();
  const { productGroups, loading } = useMarketProductGroups();

  const options = useMemo<SelectorOption<string | null>[]>(
    () => [
      { value: null, label: t("commissioning.all_market_product_groups") },
      ...productGroups.map((group) => ({
        value: group.value,
        label: group.label,
      })),
    ],
    [productGroups, t],
  );

  return (
    <BaseEntitySelector<string | null>
      value={selectedProductGroup}
      onValueChange={setSelectedProductGroup}
      options={options}
      loading={loading}
      ariaLabel={t("commissioning.filter_by_market_product_group")}
      className="bold-select week-selector-select market-product-group-selector"
      showSearch
      preserveSelection
    />
  );
};

export default MarketProductGroupSelector;
