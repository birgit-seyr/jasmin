import dayjs from "dayjs";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useTenantYearOptions } from "@hooks/index";
import SteppedSelect from "./SteppedSelect";

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

  return (
    <SteppedSelect
      value={selectedYear}
      onChange={handleYearChange}
      options={allYearOptions}
      onPrev={prevYear}
      onNext={nextYear}
      canGoPrev={canGoPrev}
      canGoNext={canGoNext}
      selectStyle={{ width: "6em" }}
      selectAriaLabel={t("common.year")}
    />
  );
};

export default YearSelector;
