import { LeftOutlined, RightOutlined } from "@ant-design/icons";
import { Button, Select, Space } from "antd";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useTenant } from "@hooks/index";

interface MonthSelectorProps {
  selectedMonth: number | "all" | null;
  setSelectedMonth: (value: number | "all") => void;
  selectedYear?: number | null;
  include_all_option?: boolean;
  useFiscalYearOrder?: boolean;
  useShortNames?: boolean;
}

const MonthSelector = ({
  selectedMonth,
  setSelectedMonth,
  selectedYear: _selectedYear = null,
  include_all_option = false,
  useFiscalYearOrder = false,
  useShortNames = false,
}: MonthSelectorProps) => {
  const { t } = useTranslation();
  const { tenant } = useTenant();

  const fiscalYearStart = tenant?.fiscal_year_start_month;

  // Generate month order based on fiscal year start
  const orderedMonths = useMemo(() => {
    if (!useFiscalYearOrder || !fiscalYearStart) {
      return Array.from({ length: 12 }, (_, i) => i + 1);
    }
    const months: number[] = [];
    for (let i = 0; i < 12; i++) {
      const month = ((fiscalYearStart - 1 + i) % 12) + 1;
      months.push(month);
    }
    return months;
  }, [fiscalYearStart, useFiscalYearOrder]);

  const getMonthLabel = useCallback(
    (month: number) => {
      const key = useShortNames
        ? `common.months_short.${month}`
        : `common.months.${month}`;
      return t(key);
    },
    [t, useShortNames],
  );

  const handleMonthChange = useCallback(
    (value: number | "all") => {
      setSelectedMonth(value);
    },
    [setSelectedMonth],
  );

  const nextMonth = useCallback(() => {
    if (selectedMonth === "all" || selectedMonth === null) {
      setSelectedMonth(orderedMonths[0]);
      return;
    }

    const currentIndex = orderedMonths.indexOf(selectedMonth);
    const nextIndex = (currentIndex + 1) % orderedMonths.length;
    setSelectedMonth(orderedMonths[nextIndex]);
  }, [selectedMonth, setSelectedMonth, orderedMonths]);

  const prevMonth = useCallback(() => {
    if (selectedMonth === "all" || selectedMonth === null) {
      return;
    }

    const currentIndex = orderedMonths.indexOf(selectedMonth);
    const prevIndex =
      currentIndex === 0 ? orderedMonths.length - 1 : currentIndex - 1;
    setSelectedMonth(orderedMonths[prevIndex]);
  }, [selectedMonth, setSelectedMonth, orderedMonths]);

  // Create month options
  const monthOptions = useMemo(() => {
    const options: { label: string; value: number | "all" }[] = [];

    if (include_all_option) {
      options.push({
        label: t("common.all_months"),
        value: "all",
      });
    }

    orderedMonths.forEach((month) => {
      options.push({
        value: month,
        label: getMonthLabel(month),
      });
    });

    return options;
  }, [orderedMonths, include_all_option, t, getMonthLabel]);

  // Check if we can navigate
  const canGoPrev = selectedMonth !== "all" && selectedMonth !== null;
  const canGoNext = true;

  const size = "small" as const;

  return (
    <Space>
      <Button
        size={size}
        icon={<LeftOutlined />}
        onClick={prevMonth}
        className="month-selector-small-buttons"
        disabled={!canGoPrev}
        aria-label={t("common.previous")}
      />
      <Select
        value={selectedMonth}
        style={{ width: "10em" }}
        size={size}
        onChange={handleMonthChange}
        options={monthOptions}
        className="bold-select month-selector-select"
        aria-label={t("common.month")}
      />
      <Button
        size={size}
        icon={<RightOutlined />}
        onClick={nextMonth}
        className="month-selector-small-buttons"
        disabled={!canGoNext}
        aria-label={t("common.next")}
      />
    </Space>
  );
};

export default MonthSelector;
