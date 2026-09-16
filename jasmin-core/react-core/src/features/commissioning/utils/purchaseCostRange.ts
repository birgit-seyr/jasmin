/**
 * The maximum date range the purchase-cost report accepts.
 *
 * ``purchase_cost_by_week`` runs one iteration per ISO week in the range and
 * widens its year/week IN-clauses to match, so the server bounds the span and
 * answers 400 (field ``end_date``) beyond it; its ``end_date`` parameter
 * documents the limit. The picker greys out what the server would refuse, so
 * the bound never has to be discovered as an error.
 *
 * KEEP IN SYNC with ``_MAX_PURCHASE_COST_SPAN_YEARS`` in
 * apps/commissioning/views/statistic_views.py. The server's own cap is stated
 * in days (5 × 366 = 1830), which is the wider of the two, so a selection this
 * module allows is always one the server serves.
 */
import type { Dayjs } from "dayjs";

export const MAX_PURCHASE_COST_RANGE_YEARS = 5;

/**
 * True when picking `current` would stretch the selection past the maximum
 * span, given the bound already chosen in the open panel. AntD hands both
 * slots of the range while it is being picked, with the open one `null`.
 */
export function isOutsidePurchaseCostRange(
  current: Dayjs,
  picked: [Dayjs | null, Dayjs | null] | null | undefined,
): boolean {
  const start = picked?.[0];
  const end = picked?.[1];
  if (
    start &&
    current.isAfter(start.add(MAX_PURCHASE_COST_RANGE_YEARS, "year"))
  ) {
    return true;
  }
  if (
    end &&
    current.isBefore(end.subtract(MAX_PURCHASE_COST_RANGE_YEARS, "year"))
  ) {
    return true;
  }
  return false;
}
