/**
 * Semantic colour ladder for the planning grid and any sibling table
 * (offers etc.) that wants the same visual hint about each row.
 *
 * Two independent ladders live here:
 *
 * - "Why is this row interesting?" — forecast / stock-only / nothing.
 *   Applied to the share-article name cell and to the unit / size /
 *   amount cells in ``usePlanningHarvestSharesColumns``.
 *
 * - "Is this row over-planned?" — over-planned / ok. Applied to the
 *   ``still_free`` cell.
 *
 * Keep the literal colour values in this one module so that:
 *   1. Sibling hooks (offers, orders) can reuse the same ladder by
 *      importing instead of re-declaring "green" / "blue" / "red".
 *   2. A future swap to CSS classes or per-tenant theming only edits
 *      this file — call sites keep their semantic names.
 */
export const planningColors = {
  /** Row was scaffolded from a Forecast. */
  forecast: "green",
  /** Row has leftover stock at week-start but no forecast and no plan. */
  stockOnly: "green",
  /** ``still_free`` went negative — over-planned. */
  overPlanned: "red",
  /** ``still_free`` is non-negative. */
  ok: "green",
  /** Default: nothing special — fall back to the surrounding text colour. */
  neutral: "inherit",
} as const;

export type PlanningColor =
  (typeof planningColors)[keyof typeof planningColors];

/**
 * Resolve the row-status colour (forecast > stockOnly > neutral) for a
 * planning row. Centralised here so the share-article cell and the
 * unit/size/amount cells stay in lockstep — if the priority order ever
 * changes, this is the only place to edit.
 */
export function planningRowColor(
  record: Record<string, unknown>,
): PlanningColor {
  // Forecast wins over stock — a forecast-attached row is the
  // actionable "we said we'd plant this" signal, while stock is a
  // hint. A row can be both (forecast that's already partially
  // covered by leftover stock); green is still the right call there.
  //
  // Read stock from ``current_stock_begin_of_week`` rather than the
  // ``is_stock_only`` flag so the hint sticks once the planner starts
  // filling in amounts. ``is_stock_only`` flips to ``false`` the
  // moment a real ``ShareContent`` exists for the slot — but the
  // stock backing it is still there, and the planner still wants the
  // visual cue.
  if (record.forecast) return planningColors.forecast;
  const stock = Number(record.current_stock_begin_of_week);
  if (Number.isFinite(stock) && stock > 0) return planningColors.stockOnly;
  return planningColors.neutral;
}

/**
 * Forecast rows get the colour AND bold weight (the planner needs them
 * to leap out — they're the "system told us to plant this" rows).
 * Stock-only rows get the colour but stay at normal weight (helpful
 * hint, not a call to action). Neutral rows fall back to whatever the
 * surrounding cell renders with.
 *
 * Kept here so that the share-article cell and the unit / size /
 * amount cells stay in lockstep — if the emphasis rule ever changes,
 * this is the only place to edit.
 */
export function planningRowFontWeight(
  record: Record<string, unknown>,
): "bold" | "normal" {
  return record.forecast ? "bold" : "normal";
}

/**
 * Convenience for callers that always want both colour + weight
 * together (share-article cell, unit/size/amount wrapper). Returns
 * a partial CSS-property object you can spread into ``style``.
 */
export function planningRowEmphasis(record: Record<string, unknown>): {
  color: PlanningColor;
  fontWeight: "bold" | "normal";
} {
  return {
    color: planningRowColor(record),
    fontWeight: planningRowFontWeight(record),
  };
}
