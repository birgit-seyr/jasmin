import { activeAtDateForWeek } from "@shared/utils";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useShareDeliveryDays } from '@features/commissioning/hooks';
import type { CommissioningSharesDeliveryDaysListParams } from "@shared/api/generated/models";
import BaseEntitySelector, { type SelectorOption } from "@shared/selectors/BaseEntitySelector";

type TourValue = number | "all";

interface TourSelectorProps {
  selectedTour: TourValue | null;
  /** Gets `null` when the chosen day lists no tours, so no stale tour stays picked. */
  setSelectedTour: (value: TourValue | null) => void;
  onTourChange?: ((value: TourValue | null) => void) | null;
  include_null_option?: boolean;
  preserveSelection?: boolean;
  delivery_day?: string | null;
  selectedYear?: number | null;
  selectedWeek?: number | null;
  /**
   * Filters for the delivery-day fetch, replacing the week's `active_at_date`.
   * Pass a memoised object: a new one each render recomputes the fetch scope.
   */
  filters?: CommissioningSharesDeliveryDaysListParams;
}

const TourSelector = ({
  selectedTour,
  setSelectedTour,
  onTourChange = null,
  include_null_option = false,
  preserveSelection = true,
  delivery_day = null,
  selectedYear = null,
  selectedWeek = null,
  filters,
}: TourSelectorProps) => {
  const { t } = useTranslation();

  const activeAtDate = useMemo(() => {
    if (!selectedYear || !selectedWeek) return null;
    return activeAtDateForWeek(selectedYear, selectedWeek);
  }, [selectedYear, selectedWeek]);

  const tourFilters = useMemo<CommissioningSharesDeliveryDaysListParams>(() => {
    if (filters && Object.keys(filters).length > 0) return filters;
    if (activeAtDate) return { active_at_date: activeAtDate };
    return {};
  }, [filters, activeAtDate]);

  const { shareDeliveryDays, loading } = useShareDeliveryDays(tourFilters);

  const numberOfTours = useMemo(() => {
    if (delivery_day === null) {
      return 0;
    }
    const record = shareDeliveryDays.find((day) => day.id === delivery_day);
    return record ? record.number_of_tours || 1 : 0;
  }, [shareDeliveryDays, delivery_day]);

  const options = useMemo<SelectorOption<TourValue | null>[]>(() => {
    if (numberOfTours === 0) return [];
    const tours: SelectorOption<TourValue | null>[] = Array.from(
      { length: numberOfTours },
      (_, i) => ({
        value: i + 1,
        label: t("commissioning.tour_number", { number: i + 1 }),
      }),
    );
    if (include_null_option) {
      tours.unshift({ value: "all", label: t("commissioning.all_tours") });
    }
    return tours;
  }, [numberOfTours, include_null_option, t]);

  return (
    <BaseEntitySelector<TourValue | null>
      value={selectedTour}
      onValueChange={setSelectedTour}
      onChange={onTourChange}
      options={options}
      loading={loading}
      placeholder={t("placeholder.tour_selector")}
      disabled={numberOfTours === 0}
      className="bold-select week-selector-select tour-selector"
      preserveSelection={preserveSelection}
      // Without a day there is nothing to check the pick against; a day
      // listing no tours drops it.
      emptyValue={delivery_day === null ? undefined : null}
      autoSelectFirst
    />
  );
};

export default TourSelector;
