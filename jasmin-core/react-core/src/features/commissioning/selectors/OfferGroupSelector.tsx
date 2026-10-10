import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useOfferGroups } from "@features/commissioning/hooks";
import BaseEntitySelector, {
  type SelectorOption,
} from "@shared/selectors/BaseEntitySelector";

interface OfferGroupSelectorProps {
  selectedOfferGroup: string | null;
  /** Gets `null` once the list loads empty, so no stale group stays picked. */
  setSelectedOfferGroup: (value: string | null) => void;
  onOfferGroupChange?: ((value: string | null) => void) | null;
  preserveSelection?: boolean;
}

const OfferGroupSelector = ({
  selectedOfferGroup,
  setSelectedOfferGroup,
  onOfferGroupChange = null,
  preserveSelection = true,
}: OfferGroupSelectorProps) => {
  const { t } = useTranslation();
  const { offerGroups, loading } = useOfferGroups();

  const options = useMemo<SelectorOption<string | null>[]>(
    () =>
      offerGroups.map((og) => ({
        value: og.value,
        label: og.label || t("commissioning.all_offer_groups"),
      })),
    [offerGroups, t],
  );

  return (
    <BaseEntitySelector<string | null>
      value={selectedOfferGroup}
      onValueChange={setSelectedOfferGroup}
      onChange={onOfferGroupChange}
      options={options}
      loading={loading}
      placeholder={t("placeholder.offer_group_selector")}
      className="bold-select week-selector-select offer-group-selector"
      autoSelectFirst
      preserveSelection={preserveSelection}
      emptyValue={null}
    />
  );
};

export default OfferGroupSelector;
