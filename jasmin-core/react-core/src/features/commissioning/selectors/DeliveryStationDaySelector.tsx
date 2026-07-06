import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useDeliveryStationDays } from "@hooks/useDeliveryStationDays";
import type { CommissioningDeliveryStationsDaysListParams } from "@shared/api/generated/models";
import BaseEntitySelector, {
  type SelectorOption,
} from "@shared/selectors/BaseEntitySelector";

interface DeliveryStationDaySelectorProps {
  selectedDeliveryStationDay: string | null;
  setSelectedDeliveryStationDay: (value: string | null) => void;
  onDeliveryStationDayChange?: ((value: string | null) => void) | null;
  /**
   * Filters forwarded to the delivery-station-day fetch (year, delivery_week,
   * delivery_station, delivery_day, …). Defaults to the current year/week
   * inside ``useDeliveryStationDays``.
   */
  params?: Partial<CommissioningDeliveryStationsDaysListParams>;
  include_null_option?: boolean;
  /**
   * Reconcile the current pick against the freshly-loaded options when they
   * change (e.g. after a day/week change): keep the selection if it still
   * exists, only fall back to the first option when it's gone — and pick the
   * first option on mount. Opt-in (default false) because some consumers
   * hand-manage the station-day state and treat a null value as "all".
   */
  preserveSelection?: boolean;
}

const DeliveryStationDaySelector = ({
  selectedDeliveryStationDay,
  setSelectedDeliveryStationDay,
  onDeliveryStationDayChange = null,
  params = {},
  include_null_option = false,
  preserveSelection = false,
}: DeliveryStationDaySelectorProps) => {
  const { t } = useTranslation();

  const { deliveryStationDays, loading } = useDeliveryStationDays(params);

  const options = useMemo<SelectorOption<string | null>[]>(() => {
    const opts: SelectorOption<string | null>[] = [];
    if (include_null_option) opts.push({ value: "none", label: "-" });
    deliveryStationDays.forEach((d) =>
      opts.push({ value: d.value, label: d.label }),
    );
    return opts;
  }, [deliveryStationDays, include_null_option]);

  return (
    <BaseEntitySelector<string | null>
      value={selectedDeliveryStationDay}
      onValueChange={setSelectedDeliveryStationDay}
      onChange={onDeliveryStationDayChange}
      options={options}
      loading={loading}
      placeholder={t("placeholder.delivery_station_day_selector")}
      style={{ width: "18em" }}
      preserveSelection={preserveSelection}
    />
  );
};

export default DeliveryStationDaySelector;
