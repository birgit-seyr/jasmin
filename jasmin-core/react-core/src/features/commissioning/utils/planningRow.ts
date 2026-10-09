/**
 * Typed reads of a harvest share planning row. The grid hands its rows around
 * as `TableRecord` (every field `unknown`, since a row also carries its dynamic
 * `day_*` cells), so the fields the planning code computes with are read here
 * with a runtime check instead of a cast at every call site.
 */
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";

/** The row's unit (`KG`, `PCS`, `BUNCH`, …), or undefined on a row without one. */
export function planningRowUnit(record: TableRecord): string | undefined {
  return typeof record.unit === "string" ? record.unit : undefined;
}

/** The unit the row's forecast is counted in, falling back to the row's. */
export function planningRowForecastUnit(record: TableRecord): string | undefined {
  return typeof record.forecast_unit === "string"
    ? record.forecast_unit
    : planningRowUnit(record);
}

/**
 * The forecast amount available to the row, in the row's own unit. The
 * backend gives each (article, unit, size) row the forecast of exactly that
 * slot, so the units always agree; a forecast in another unit belongs to
 * another row and counts as nothing here rather than being added to amounts
 * it can't be compared with.
 */
export function forecastAmountInRowUnit(record: TableRecord): number {
  const unit = planningRowUnit(record);
  if (unit === undefined || record.forecast_unit !== unit) return 0;
  return parseFloat(String(record.forecast_available_amount)) || 0;
}

// The article weight field a piece or a bunch of each size is converted to kg
// with: `kg_per_piece_<size>` / `kg_per_bunch_<size>`. KG needs no conversion.
const ITEM_WEIGHT_FIELD_BASE: Record<string, string> = {
  PCS: "kg_per_piece",
  BUNCH: "kg_per_bunch",
};

/**
 * The kg one unit of the row weighs: 1 for KG, the row's own `kg_per_piece`
 * when set, otherwise the article's per-piece or per-bunch weight for the
 * row's size. 0 when no weight is known.
 */
export function kgPerRowUnit(record: TableRecord): number {
  const unit = planningRowUnit(record);
  if (unit === "KG") return 1;
  const rowOverride = parseFloat(String(record.kg_per_piece)) || 0;
  if (rowOverride) return rowOverride;
  const base = unit === undefined ? undefined : ITEM_WEIGHT_FIELD_BASE[unit];
  const size = record.size;
  if (!base || typeof size !== "string") return 0;
  return Number(record[`${base}_${size}`]) || 0;
}
