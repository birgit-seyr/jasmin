import { Select, Space } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useIsMobile, useDeliveryDayLabel } from "@hooks/index";
import { dateForWeekDayNumber } from "@shared/utils";
import SteppedSelect from "./SteppedSelect";

const { Option } = Select;

/**
 * ``TDay`` is the page's own day type — plain ``number`` by default, or a
 * narrower one such as the backend's ``DayNumberEnum``, which ``days`` then
 * has to list and ``setSelectedDay`` receives unchanged.
 */
interface DaySelectorProps<TDay extends number = number> {
  selectedDay: TDay | null;
  setSelectedDay: (day: TDay | null) => void;
  selectedWeek: number;
  selectedYear: number;
  days: (TDay | null)[];
  suffix?: string | null;
  include_null_option?: boolean;
  usesDaysWithOrders?: boolean;
  daysWithOrders?: number[];
  daysWithLabels?: number[];
  daysWithDeliveryNotes?: number[];
  customDateCalculator?: ((day: TDay | null) => string) | null;
}

export default function DaySelector<TDay extends number = number>({
  selectedDay,
  setSelectedDay,
  selectedWeek,
  selectedYear,
  days,
  suffix = null,
  include_null_option = false,
  usesDaysWithOrders = false,
  daysWithOrders = [],
  daysWithLabels: _daysWithLabels = [],
  daysWithDeliveryNotes: _daysWithDeliveryNotes = [],
  customDateCalculator = null,
}: DaySelectorProps<TDay>) {
  const handleDayChange = (value: TDay | null) => {
    setSelectedDay(value);
  };

  const { t } = useTranslation();
  const isMobile = useIsMobile();
  const deliveryDayLabel = useDeliveryDayLabel();

  const calculateDate = (day: TDay | null, week = selectedWeek) => {
    if (customDateCalculator) {
      return customDateCalculator(day);
    }
    if (day === null) return "";
    return deliveryDayLabel(selectedYear, week, day);
  };

  const nextDay = useCallback(() => {
    if (days.length === 0) return;

    const validDays = days.filter((day): day is TDay => day !== null);
    const currentIndex = validDays.indexOf(selectedDay!);

    if (currentIndex < validDays.length - 1) {
      setSelectedDay(validDays[currentIndex + 1]);
    }
  }, [selectedDay, days, setSelectedDay]);

  const prevDay = useCallback(() => {
    if (days.length === 0) return;

    const validDays = days.filter((day): day is TDay => day !== null);
    const currentIndex = validDays.indexOf(selectedDay!);

    if (currentIndex > 0) {
      setSelectedDay(validDays[currentIndex - 1]);
    }
  }, [selectedDay, days, setSelectedDay]);

  // Create options array with null option if requested
  const dayOptions = useMemo(() => {
    let options: (TDay | null)[] = [];

    if (include_null_option) {
      options.push(null);
    }

    const validDays = days.filter((day): day is TDay => day !== null);

    const sortedValidDays = [...validDays].sort((a, b) => {
      if (customDateCalculator) {
        const dateA = customDateCalculator(a);
        const dateB = customDateCalculator(b);
        return dayjs(dateA).valueOf() - dayjs(dateB).valueOf();
      }

      const dateA = dateForWeekDayNumber(selectedYear, selectedWeek, a);
      const dateB = dateForWeekDayNumber(selectedYear, selectedWeek, b);

      return dateA.valueOf() - dateB.valueOf();
    });

    options = [...options, ...sortedValidDays];

    return options;
  }, [days, include_null_option, customDateCalculator, selectedYear, selectedWeek]);

  const validDays = days.filter((day): day is TDay => day !== null);

  // Check if we can navigate (only consider non-null days for navigation)
  const currentIndex = validDays.indexOf(selectedDay!);
  const canGoPrev = currentIndex > 0;
  const canGoNext = currentIndex < validDays.length - 1;

  return (
    <Space>
      <SteppedSelect
        showDivider
        value={selectedDay}
        onChange={handleDayChange}
        onPrev={prevDay}
        onNext={nextDay}
        canGoPrev={canGoPrev}
        canGoNext={canGoNext}
        selectStyle={{
          width: isMobile ? "10em" : suffix === null ? "15em" : "22em",
        }}
        selectAriaLabel={t("common.delivery_day")}
      >
        {dayOptions.map((day) => (
          <Option
            key={day === null ? "none" : day}
            value={day}
            className={
              day !== null && usesDaysWithOrders && daysWithOrders.includes(day)
                ? "with-orders"
                : day !== null && usesDaysWithOrders
                  ? "without-orders"
                  : undefined
            }
          >
            {day === null ? (
              t("commissioning.all_delivery_days")
            ) : (
              <>
                {!isMobile && suffix ? `${suffix} ` : ""}
                {calculateDate(day)}
              </>
            )}
          </Option>
        ))}
      </SteppedSelect>
    </Space>
  );
}
