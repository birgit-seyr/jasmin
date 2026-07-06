import dayjs, { type Dayjs } from "dayjs";
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
  const end = (range ? range[1] : dayjs()).startOf("month");
  const selStart = (range ? range[0] : dayjs().subtract(1, "year")).startOf(
    "month",
  );
  const minStart = end.subtract(11, "month");
  let cursor = selStart.isBefore(minStart) ? selStart : minStart;

  const byMonth = new Map<string, number>();
  for (const p of points ?? []) {
    byMonth.set(p.month, Number.parseFloat(p.amount) || 0);
  }

  const data: Array<Record<string, number | string>> = [];
  while (!cursor.isAfter(end)) {
    data.push({
      label: cursor.format("MMM 'YY"),
      [series.id]: byMonth.get(cursor.format("YYYY-MM")) ?? 0,
    });
    cursor = cursor.add(1, "month");
  }
  return { data, series: [series] };
}
