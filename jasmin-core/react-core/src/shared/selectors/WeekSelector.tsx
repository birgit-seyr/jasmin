import { Select, Space } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useTenantYearOptions } from "@hooks/index";
import SteppedSelect from "./SteppedSelect";

interface WeekSelectorProps {
  selectedYear: number;
  setSelectedYear: (value: number) => void;
  selectedWeek: number | null;
  setSelectedWeek: (value: number | null) => void;
  include_null_option?: boolean;
}

const WeekSelector = ({
  selectedYear,
  setSelectedYear,
  selectedWeek,
  setSelectedWeek,
  include_null_option = false,
}: WeekSelectorProps) => {
  const { t } = useTranslation();
  const { tenantCreationYear, yearOptions } = useTenantYearOptions();

  const handleYearChange = useCallback(
    (value: number) => {
      setSelectedYear(value);
    },
    [setSelectedYear],
  );

  const handleWeekChange = useCallback(
    (value: number | null) => {
      setSelectedWeek(value);
    },
    [setSelectedWeek],
  );

  const getWeeksInYear = (year: number) => {
    const lastDayOfYear = dayjs(`${year}-12-31`);
    const lastWeek = lastDayOfYear.isoWeek();
    return lastWeek === 1 ? 52 : lastWeek;
  };

  const nextWeek = useCallback(() => {
    if (selectedWeek === null) {
      setSelectedWeek(1);
      return;
    }

    const weeksInCurrentYear = getWeeksInYear(selectedYear);

    if (selectedWeek < weeksInCurrentYear) {
      setSelectedWeek(selectedWeek + 1);
    } else {
      setSelectedYear(selectedYear + 1);
      setSelectedWeek(1);
    }
  }, [selectedYear, selectedWeek, setSelectedYear, setSelectedWeek]);

  const prevWeek = useCallback(() => {
    if (selectedWeek === null) {
      return;
    }

    if (selectedWeek > 1) {
      setSelectedWeek(selectedWeek - 1);
      return;
    }

    if (selectedWeek === 1) {
      const prevYear = selectedYear - 1;

      if (prevYear < tenantCreationYear) {
        return;
      }

      const weeksInPrevYear = getWeeksInYear(prevYear);

      setSelectedYear(prevYear);
      setSelectedWeek(weeksInPrevYear);
    }
  }, [
    selectedYear,
    selectedWeek,
    setSelectedYear,
    setSelectedWeek,
    tenantCreationYear,
  ]);

  const weeksInYear = getWeeksInYear(selectedYear);

  const weekOptions = useMemo(() => {
    const options: { label: string; value: number | null }[] = [];

    if (include_null_option) {
      options.push({
        label: t("commissioning.all_delivery_weeks"),
        value: null,
      });
    }

    for (let i = 0; i < weeksInYear; i++) {
      options.push({
        label: t("commissioning.week_short", { number: i + 1 }),
        value: i + 1,
      });
    }

    return options;
  }, [weeksInYear, t, include_null_option]);

  const canGoPrev =
    selectedWeek !== null &&
    (selectedWeek > 1 ||
      (selectedWeek === 1 && selectedYear > tenantCreationYear));

  const canGoNext = true;

  return (
    <Space>
      <Select
        value={selectedYear}
        style={{ width: "6em" }}
        size="small"
        onChange={handleYearChange}
        options={yearOptions}
        className="week-selector-select"
        aria-label={t("common.year")}
      />
      <SteppedSelect
        showDivider
        value={selectedWeek}
        onChange={handleWeekChange}
        options={weekOptions}
        onPrev={prevWeek}
        onNext={nextWeek}
        canGoPrev={canGoPrev}
        canGoNext={canGoNext}
        selectStyle={
          include_null_option
            ? { width: "6.5em", textAlign: "center" }
            : { width: "6em" }
        }
        selectAriaLabel={t("common.week")}
      />
    </Space>
  );
};

export default WeekSelector;
