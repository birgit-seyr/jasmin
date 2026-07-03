import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useOfferGroups } from "@features/commissioning/hooks";
import BaseEntitySelector, {
  type SelectorOption,
} from "@shared/selectors/BaseEntitySelector";

interface OfferGroupSelectorProps {
  selectedOfferGroup: string | null;
  setSelectedOfferGroup: (value: string) => void;
  onOfferGroupChange?: ((value: string) => void) | null;
  include_null_option?: boolean;
  preserveSelection?: boolean;
}

const OfferGroupSelector = ({
  selectedOfferGroup,
  setSelectedOfferGroup,
  onOfferGroupChange = null,
  preserveSelection = true,
}: OfferGroupSelectorProps) => {
  const { t } = useTranslation();
  const { offerGroups, loading, error } = useOfferGroups();

  const options = useMemo<SelectorOption<string>[]>(
    () =>
      offerGroups.map((og) => ({
        value: og.value,
        label: og.label || t("commissioning.all_offer_groups"),
      })),
    [offerGroups, t],
  );

  if (error) {
    console.error("Error in OfferGroupSelector:", error);
  }

  return (
    <BaseEntitySelector<string>
      value={selectedOfferGroup}
      onValueChange={setSelectedOfferGroup}
      onChange={onOfferGroupChange}
      options={options}
      loading={loading}
      placeholder={t("placeholder.offer_group_selector")}
      style={{ width: "12em", marginLeft: "0em", marginTop: "2em" }}
      autoSelectFirst
      preserveSelection={preserveSelection}
    />
  );
};

export default OfferGroupSelector;
