import { LeftOutlined, RightOutlined } from "@ant-design/icons";
import { Button, Select, Space } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useTenantYearOptions } from "@hooks/index";

interface YearSelectorProps {
  selectedYear: number | null;
  setSelectedYear: (value: number) => void;
  include_null_option?: boolean;
}

const YearSelector = ({
  selectedYear,
  setSelectedYear,
  include_null_option = false,
}: YearSelectorProps) => {
  const { t } = useTranslation();
  const { tenantCreationYear, yearOptions } = useTenantYearOptions();

  const currentYear = dayjs().year();

  const handleYearChange = useCallback(
    (value: number) => {
      setSelectedYear(value);
    },
    [setSelectedYear],
  );

  const nextYear = useCallback(() => {
    if (selectedYear === null) {
      setSelectedYear(currentYear);
      return;
    }
    setSelectedYear(selectedYear + 1);
  }, [selectedYear, setSelectedYear, currentYear]);

  const prevYear = useCallback(() => {
    if (selectedYear === null) return;
    const prev = selectedYear - 1;
    if (prev < tenantCreationYear) return;
    setSelectedYear(prev);
  }, [selectedYear, setSelectedYear, tenantCreationYear]);

  const allYearOptions = useMemo(() => {
    const options: { label: string | number; value: number | null }[] = [];

    if (include_null_option) {
      options.push({
        label: "All Years",
        value: null,
      });
    }

    options.push(...yearOptions);
    return options;
  }, [yearOptions, include_null_option]);

  const canGoPrev = selectedYear !== null && selectedYear > tenantCreationYear;
  const canGoNext = true;

  const size = "small" as const;

  return (
    <Space>
      <Button
        size={size}
        icon={<LeftOutlined />}
        onClick={prevYear}
        className="week-selector-small-buttons"
        disabled={!canGoPrev}
        aria-label={t("common.previous")}
      />
      <Select
        value={selectedYear}
        style={{ width: "6em" }}
        size={size}
        onChange={handleYearChange}
        options={allYearOptions}
        className="bold-select week-selector-select"
        aria-label={t("common.year")}
      />
      <Button
        size={size}
        icon={<RightOutlined />}
        onClick={nextYear}
        className="week-selector-small-buttons"
        disabled={!canGoNext}
        aria-label={t("common.next")}
      />
    </Space>
  );
};

export default YearSelector;
