import { useCallback, useEffect, useMemo } from "react";
import type { ReactNode } from "react";
import { Button, Divider, Flex, Select, Space } from "antd";
import { LeftOutlined, RightOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { useDateFormat, useDeliveryDayLabel, useIsMobile } from '@hooks/index';
import { activeAtDateForWeek, getStatusColor } from "@shared/utils";
import { useShareDeliveryDays } from '@features/commissioning/hooks';

const { Option } = Select;

interface SharesDeliveryDaySelectorProps {
  selectedSharesDeliveryDay: string | null;
  setSelectedSharesDeliveryDay: (value: string | null) => void;
  onSharesDeliveryDayChange?:
    | ((value: string | null, selectedDay?: unknown) => void)
    | null;
  include_null_option?: boolean;
  preserveSelection?: boolean;
  active_at_date?: string;
  selectedYear?: number;
  selectedWeek?: number | null;
  suffix?: string | null;
}

const SharesDeliveryDaySelector = ({
  selectedSharesDeliveryDay,
  setSelectedSharesDeliveryDay,
  onSharesDeliveryDayChange = null,
  include_null_option = false,
  preserveSelection = true,
  active_at_date,
  selectedYear,
  selectedWeek,
  suffix = null,
}: SharesDeliveryDaySelectorProps) => {
  const { t } = useTranslation();
  const { formatDate } = useDateFormat();
  const isMobile = useIsMobile();
  const deliveryDayLabel = useDeliveryDayLabel();

  const useDayFormat = !!selectedYear && !!selectedWeek;

  // Scope the fetch to the selected week (its Saturday) so only that week's
  // ACTIVE delivery days show — not stale/duplicate time-bound records (e.g. two
  // Fridays). An explicit ``active_at_date`` prop still wins.
  const effectiveActiveAtDate =
    active_at_date ??
    (selectedYear && selectedWeek
      ? activeAtDateForWeek(selectedYear, selectedWeek)
      : undefined);
  const { shareDeliveryDays, loading } = useShareDeliveryDays(
    effectiveActiveAtDate ? { active_at_date: effectiveActiveAtDate } : {},
  );

  // Enrich delivery days with labels and status colors
  // (status color via the shared ``getStatusColor``).
  const enrichedDays = useMemo(() => {
    return shareDeliveryDays.map((day) => {
      const validFrom = formatDate(day.valid_from);
      const validUntil = formatDate(day.valid_until);

      let datePart = "";
      if (validFrom) {
        datePart = `${t("commissioning.valid_from")} ${validFrom}`;
      }
      if (validUntil) {
        datePart += ` ${t("commissioning.valid_until")} ${validUntil}`;
      }

      return {
        ...day,
        datePart,
        statusColor: getStatusColor(day.valid_from, day.valid_until),
      };
    });
  }, [shareDeliveryDays, formatDate, t]);

  // Handle default selection
  useEffect(() => {
    if (loading || !enrichedDays.length) return;

    if (preserveSelection) {
      const currentExists = enrichedDays.some(
        (d) => d.id === selectedSharesDeliveryDay,
      );
      if (!selectedSharesDeliveryDay || !currentExists) {
        const defaultValue = include_null_option
          ? null
          : (enrichedDays[0]?.id ?? null);
        setSelectedSharesDeliveryDay(defaultValue);
      }
    } else {
      setSelectedSharesDeliveryDay(enrichedDays[0]?.id ?? null);
    }
  }, [
    enrichedDays,
    loading,
    selectedSharesDeliveryDay,
    setSelectedSharesDeliveryDay,
    preserveSelection,
    include_null_option,
  ]);

  // Compute date label for a delivery day in the selected week
  const calculateDate = useCallback(
    (dayNumber: number | null | undefined) => {
      if (!selectedYear || !selectedWeek || dayNumber == null) return "";
      return deliveryDayLabel(selectedYear, selectedWeek, dayNumber);
    },
    [selectedYear, selectedWeek, deliveryDayLabel],
  );

  // Sort enriched days by day_number for navigation
  const sortedDays = useMemo(() => {
    return [...enrichedDays].sort(
      (a, b) => (a.day_number as number) - (b.day_number as number),
    );
  }, [enrichedDays]);

  const currentIndex = sortedDays.findIndex(
    (d) => d.id === selectedSharesDeliveryDay,
  );
  const canGoPrev = currentIndex > 0;
  const canGoNext = currentIndex < sortedDays.length - 1;

  const prevDay = useCallback(() => {
    if (canGoPrev) {
      const prev = sortedDays[currentIndex - 1];
      setSelectedSharesDeliveryDay(prev.id!);
      if (onSharesDeliveryDayChange) onSharesDeliveryDayChange(prev.id!, prev);
    }
  }, [
    canGoPrev,
    sortedDays,
    currentIndex,
    setSelectedSharesDeliveryDay,
    onSharesDeliveryDayChange,
  ]);

  const nextDay = useCallback(() => {
    if (canGoNext) {
      const next = sortedDays[currentIndex + 1];
      setSelectedSharesDeliveryDay(next.id!);
      if (onSharesDeliveryDayChange) onSharesDeliveryDayChange(next.id!, next);
    }
  }, [
    canGoNext,
    sortedDays,
    currentIndex,
    setSelectedSharesDeliveryDay,
    onSharesDeliveryDayChange,
  ]);

  const sharesDeliveryDayOptions = useMemo(() => {
    const options: { value: string | null; label: ReactNode }[] = [];

    if (include_null_option) {
      options.push({ value: null, label: "-" });
    }

    enrichedDays.forEach((day) => {
      if (useDayFormat) {
        options.push({
          value: day.id!,
          label: calculateDate(day.day_number),
        });
      } else {
        options.push({
          value: day.id!,
          label: (
            <Flex align="center" component="span">
              {day.statusColor ? (
                <span
                  style={{
                    display: "inline-block",
                    width: "10px",
                    height: "10px",
                    backgroundColor: day.statusColor,
                    marginRight: "8px",
                    borderRadius: "2px",
                  }}
                />
              ) : null}
              {day.label}
              {day.datePart ? (
                <span
                  style={{
                    color: "var(--color-text-muted)",
                    fontSize: "0.85em",
                    marginLeft: "8px",
                  }}
                >
                  {day.datePart}
                </span>
              ) : null}
            </Flex>
          ),
        });
      }
    });

    return options;
  }, [enrichedDays, include_null_option, useDayFormat, calculateDate]);

  const handleSharesDeliveryDayChange = useCallback(
    (value: string | null) => {
      setSelectedSharesDeliveryDay(value);
      if (onSharesDeliveryDayChange) {
        const selectedDay = enrichedDays.find((day) => day.id === value);
        onSharesDeliveryDayChange(value, selectedDay);
      }
    },
    [setSelectedSharesDeliveryDay, onSharesDeliveryDayChange, enrichedDays],
  );

  if (useDayFormat) {
    return (
      <Space>
        <Space>
          <Divider type="vertical" />
          <Button
            size="small"
            icon={<LeftOutlined />}
            onClick={prevDay}
            className="week-selector-small-buttons"
            disabled={!canGoPrev}
            aria-label={t("common.previous")}
          />
          <Select
            value={selectedSharesDeliveryDay}
            style={{ width: isMobile ? "10em" : suffix ? "22em" : "15em" }}
            size="small"
            onChange={handleSharesDeliveryDayChange}
            className="bold-select week-selector-select"
            placeholder={t("placeholder.shares_delivery_day_selector")}
            aria-label={t("placeholder.shares_delivery_day_selector")}
            loading={loading}
          >
            {include_null_option && (
              <Option key="none" value={null}>
                {t("commissioning.all_delivery_days")}
              </Option>
            )}
            {sortedDays.map((day) => (
              <Option key={day.id} value={day.id}>
                {!isMobile && suffix ? `${suffix} ` : ""}
                {calculateDate(day.day_number)}
              </Option>
            ))}
          </Select>
          <Button
            size="small"
            icon={<RightOutlined />}
            onClick={nextDay}
            className="week-selector-small-buttons"
            disabled={!canGoNext}
            aria-label={t("common.next")}
          />
        </Space>
      </Space>
    );
  }

  return (
    <Select
      value={selectedSharesDeliveryDay}
      style={{ width: "30em" }}
      size="small"
      onChange={handleSharesDeliveryDayChange}
      options={sharesDeliveryDayOptions}
      className="bold-select week-selector-select"
      placeholder={t("placeholder.shares_delivery_day_selector")}
      aria-label={t("placeholder.shares_delivery_day_selector")}
      loading={loading}
    />
  );
};

export default SharesDeliveryDaySelector;
