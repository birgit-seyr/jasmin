import { LeftOutlined, RightOutlined } from "@ant-design/icons";
import { Button, Divider, Select, Space } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useTenantYearOptions } from "@hooks/index";

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

  const size = "small" as const;

  return (
    <Space>
      <Select
        value={selectedYear}
        style={{ width: "6em" }}
        size={size}
        onChange={handleYearChange}
        options={yearOptions}
        className="week-selector-select"
        aria-label={t("common.year")}
      />
      <Space>
        <Divider type="vertical" />
        <Button
          size={size}
          icon={<LeftOutlined />}
          onClick={prevWeek}
          className="week-selector-small-buttons"
          disabled={!canGoPrev}
          aria-label={t("common.previous")}
        />
        <Select
          style={
            include_null_option
              ? { width: "6.5em", textAlign: "center" }
              : { width: "6em" }
          }
          size={size}
          onChange={handleWeekChange}
          className="bold-select week-selector-select"
          value={selectedWeek}
          options={weekOptions}
          aria-label={t("common.week")}
        />
        <Button
          size={size}
          icon={<RightOutlined />}
          onClick={nextWeek}
          className="week-selector-small-buttons"
          disabled={!canGoNext}
          aria-label={t("common.next")}
        />
      </Space>
    </Space>
  );
};

export default WeekSelector;
