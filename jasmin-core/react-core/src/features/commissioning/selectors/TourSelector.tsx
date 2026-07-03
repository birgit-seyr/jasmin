import dayjs from "dayjs";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useShareDeliveryDays } from '@features/commissioning/hooks';
import BaseEntitySelector, { type SelectorOption } from "@shared/selectors/BaseEntitySelector";

interface TourSelectorProps {
  selectedTour: number | "all" | null;
  setSelectedTour: (value: number | "all") => void;
  onTourChange?: ((value: number | "all") => void) | null;
  include_null_option?: boolean;
  preserveSelection?: boolean;
  delivery_day?: string | null;
  selectedYear?: number | null;
  selectedWeek?: number | null;
  filters?: Record<string, unknown>;
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
  filters = {},
}: TourSelectorProps) => {
  const { t } = useTranslation();

  const activeAtDate = useMemo(() => {
    if (!selectedYear || !selectedWeek) return null;
    return dayjs()
      .year(selectedYear)
      .isoWeek(selectedWeek)
      .isoWeekday(6)
      .format("YYYY-MM-DD");
  }, [selectedYear, selectedWeek]);

  const tourFilters = useMemo(() => {
    if (filters && Object.keys(filters).length > 0) return filters;
    if (activeAtDate) return { active_at_date: activeAtDate };
    return {};
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(filters), activeAtDate]);

  const { shareDeliveryDays, toursByDay, loading, error } =
    useShareDeliveryDays(
      tourFilters as Parameters<typeof useShareDeliveryDays>[0],
    );

  const numberOfTours = useMemo(() => {
    if (!toursByDay || delivery_day === null || delivery_day === undefined) {
      return 0;
    }
    const record = shareDeliveryDays.find((day) => day.id === delivery_day);
    return record ? record.number_of_tours || 1 : 0;
  }, [shareDeliveryDays, delivery_day, toursByDay]);

  const options = useMemo<SelectorOption<number | "all">[]>(() => {
    if (numberOfTours === 0) return [];
    const tours: SelectorOption<number | "all">[] = Array.from(
      { length: numberOfTours },
      (_, i) => ({
        value: (i + 1) as number,
        label: t("commissioning.tour_number", { number: i + 1 }),
      }),
    );
    if (include_null_option) {
      tours.unshift({ value: "all", label: t("commissioning.all_tours") });
    }
    return tours;
  }, [numberOfTours, include_null_option, t]);

  if (error) {
    console.error("Error in TourSelector:", error);
  }

  return (
    <BaseEntitySelector<number | "all">
      value={selectedTour}
      onValueChange={setSelectedTour}
      onChange={onTourChange}
      options={options}
      loading={loading}
      disabled={numberOfTours === 0}
      style={{ width: "8em", marginTop: "1em", marginBottom: "1.5em" }}
      preserveSelection={preserveSelection}
      autoSelectFirst
    />
  );
};

export default TourSelector;
