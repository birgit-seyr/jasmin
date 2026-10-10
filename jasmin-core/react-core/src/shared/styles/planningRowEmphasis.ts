/**
 * Why a planning row is interesting — scaffolded from a forecast, backed by
 * leftover stock, or neither — and the CSS class that shows it. Applied to
 * the share-article name cell and to the unit / size / amount cells in
 * ``usePlanningHarvestSharesColumns``, so they stay in lockstep.
 */
export type PlanningRowStatus = "forecast" | "stock" | "neutral";

/**
 * Forecast wins over stock: a forecast-attached row is the actionable "we
 * said we'd plant this" signal, while stock is a hint. Stock is read from
 * ``current_stock_begin_of_week`` rather than ``is_stock_only``, which turns
 * false as soon as a real ``ShareContent`` exists for the slot although the
 * stock backing it is still there and the planner still wants the cue.
 */
export function planningRowStatus(
  record: Record<string, unknown>,
): PlanningRowStatus {
  if (record.forecast) return "forecast";
  const stock = Number(record.current_stock_begin_of_week);
  if (Number.isFinite(stock) && stock > 0) return "stock";
  return "neutral";
}

const EMPHASIS_CLASS: Record<PlanningRowStatus, string | undefined> = {
  forecast: "planning-row-forecast",
  stock: "planning-row-stock",
  neutral: undefined,
};

/**
 * The class a planning row's highlighted cells render with: forecast rows in
 * the highlight colour and bold (a call to action), stock rows in the colour
 * at normal weight (a hint), anything else unstyled.
 */
export function planningRowEmphasisClass(
  record: Record<string, unknown>,
): string | undefined {
  return EMPHASIS_CLASS[planningRowStatus(record)];
}
