import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useDeliveryStations } from '@features/commissioning/hooks';
import BaseEntitySelector, { type SelectorOption } from "@shared/selectors/BaseEntitySelector";

interface DeliveryStationSelectorProps {
  selectedDeliveryStation: string | null;
  setSelectedDeliveryStation: (value: string | null) => void;
  onDeliveryStationChange?: ((value: string | null) => void) | null;
  delivery_day?: string | null;
  include_null_option?: boolean;
  /**
   * Reconcile the current pick against the freshly-loaded options when they
   * change (e.g. after a day/week change): keep the selection if it still
   * exists, only fall back to the first option when it's gone — and pick the
   * first option on mount. Opt-in (default false) because some consumers
   * (PackingList) hand-manage the station state and treat a null station as
   * "all stations"; flipping it on there would silently filter to one
   * station. Pages that want a station always selected pass true.
   */
  preserveSelection?: boolean;
  /**
   * List EVERY active station regardless of ``delivery_day`` (for day-agnostic
   * pages like ShareDeliveries). Without it the fetch waits for a
   * ``delivery_day`` and the dropdown is empty on a page that has none.
   */
  allStations?: boolean;
}

const DeliveryStationSelector = ({
  selectedDeliveryStation,
  setSelectedDeliveryStation,
  onDeliveryStationChange = null,
  delivery_day = null,
  include_null_option = false,
  preserveSelection = false,
  allStations = false,
}: DeliveryStationSelectorProps) => {
  const { t } = useTranslation();

  const { deliveryStations, loading } = useDeliveryStations(
    { delivery_day: delivery_day ?? undefined },
    { enabled: allStations || delivery_day != null },
  );

  const options = useMemo<SelectorOption<string | null>[]>(() => {
    const opts: SelectorOption<string | null>[] = [];
    if (include_null_option) opts.push({ value: "none", label: "-" });
    deliveryStations.forEach((s) =>
      opts.push({ value: s.value, label: s.label }),
    );
    return opts;
  }, [deliveryStations, include_null_option]);

  return (
    <BaseEntitySelector<string | null>
      value={selectedDeliveryStation}
      onValueChange={setSelectedDeliveryStation}
      onChange={onDeliveryStationChange}
      options={options}
      loading={loading}
      placeholder={t("placeholder.delivery_station_selector")}
      style={{ width: "18em", marginLeft: "2em", marginRight: "2em" }}
      preserveSelection={preserveSelection}
    />
  );
};

export default DeliveryStationSelector;
