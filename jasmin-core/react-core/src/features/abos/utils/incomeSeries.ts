import type { Dayjs } from "dayjs";
import { buildMonthAxis } from "@shared/utils";
import type { StatsAreaSeries } from "@shared/ui";

/** One (month, amount-string) point as returned by the income_by_month endpoint. */
export interface MonthlyIncomePoint {
  month: string; // "YYYY-MM"
  amount: string; // 2dp money string
}

/**
 * Map the backend's per-month billed-income points onto the StatsAreaChart
 * shape, zero-filling every month in the window so the line is continuous.
 *
 * The month axis mirrors {@link buildMonthlyActiveByVariation} exactly (the
 * selected range, but always at least the last 12 months) so this chart lines
 * up with the active-subscriptions chart above it. The money string is parsed
 * to a number for plotting only — display-side, never persisted.
 */
export function buildMonthlyIncomeSeries(
  points: MonthlyIncomePoint[] | undefined,
  range: [Dayjs, Dayjs] | null,
  series: StatsAreaSeries,
): { data: Array<Record<string, number | string>>; series: StatsAreaSeries[] } {
  const { months, labelOf } = buildMonthAxis(range);

  const byMonth = new Map<string, number>();
  for (const p of points ?? []) {
    byMonth.set(p.month, Number.parseFloat(p.amount) || 0);
  }

  const data: Array<Record<string, number | string>> = months.map((month) => ({
    label: labelOf(month),
    [series.id]: byMonth.get(month.format("YYYY-MM")) ?? 0,
  }));
  return { data, series: [series] };
}
