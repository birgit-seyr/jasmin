import dayjs, { type Dayjs } from "dayjs";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

export interface DateRangePreset {
  label: string;
  value: [Dayjs, Dayjs];
}

/**
 * Standard date range presets used by CSV export modals
 * (this month / last month / this year / last year).
 */
export function useDateRangePresets(): DateRangePreset[] {
  const { t } = useTranslation();
  return useMemo(
    () => [
      {
        label: t("common.this_month"),
        value: [dayjs().startOf("month"), dayjs().endOf("month")],
      },
      {
        label: t("common.last_month"),
        value: [
          dayjs().subtract(1, "month").startOf("month"),
          dayjs().subtract(1, "month").endOf("month"),
        ],
      },
      {
        label: t("common.this_year"),
        value: [dayjs().startOf("year"), dayjs().endOf("year")],
      },
      {
        label: t("common.last_year"),
        value: [
          dayjs().subtract(1, "year").startOf("year"),
          dayjs().subtract(1, "year").endOf("year"),
        ],
      },
    ],
    [t],
  );
}
