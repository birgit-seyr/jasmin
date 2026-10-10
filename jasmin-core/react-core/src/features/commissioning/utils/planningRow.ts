/**
 * Typed reads of a harvest share planning row. The grid hands its rows around
 * as `TableRecord` (every field `unknown`, since a row also carries its dynamic
 * `day_*` cells), so the fields the planning code computes with are read here
 * with a runtime check instead of a cast at every call site.
 */
import type { ShareArticle } from "@shared/api/generated/models";
import { UnitEnum, VegetableSizeEnum } from "@shared/api/generated/models";
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

const UNITS: readonly string[] = Object.values(UnitEnum);
const SIZES: readonly string[] = Object.values(VegetableSizeEnum);

function isUnit(value: unknown): value is UnitEnum {
  return typeof value === "string" && UNITS.includes(value);
}

function isSize(value: unknown): value is VegetableSizeEnum {
  return typeof value === "string" && SIZES.includes(value);
}

type ArticlePriceField =
  | "net_price_for_boxes_kg"
  | "net_price_for_boxes_pieces"
  | "net_price_for_boxes_bunch";

type ArticleWeightField =
  | `kg_per_piece_${VegetableSizeEnum}`
  | `kg_per_bunch_${VegetableSizeEnum}`;

/**
 * The article fields a unit is priced and weighed from: the net box price
 * (the source of a planning row's `price_per_unit`, as in the backend's
 * per-unit fallback in ShareContentService) and the per-item weight base
 * (`kg_per_piece_<size>` / `kg_per_bunch_<size>`). KG has no per-item weight,
 * since its amount is already in kg; L and G are neither priced nor weighed.
 */
const ARTICLE_FIELDS_BY_UNIT: Partial<
  Record<
    UnitEnum,
    { price: ArticlePriceField; weightBase: "kg_per_piece" | "kg_per_bunch" | null }
  >
> = {
  KG: { price: "net_price_for_boxes_kg", weightBase: null },
  PCS: { price: "net_price_for_boxes_pieces", weightBase: "kg_per_piece" },
  BUNCH: { price: "net_price_for_boxes_bunch", weightBase: "kg_per_bunch" },
};

/** The article's net box price field for the unit, if the unit is priced. */
export function articlePriceField(unit: unknown): ArticlePriceField | undefined {
  return isUnit(unit) ? ARTICLE_FIELDS_BY_UNIT[unit]?.price : undefined;
}

/**
 * The article's weight field one item of the unit and size weighs: the
 * per-piece weight for PCS, the per-bunch weight for BUNCH. Undefined for KG,
 * for an unweighed unit and without a known size.
 */
export function articleWeightField(
  unit: unknown,
  size: unknown,
): ArticleWeightField | undefined {
  const base = isUnit(unit) ? ARTICLE_FIELDS_BY_UNIT[unit]?.weightBase : undefined;
  if (!base || !isSize(size)) return undefined;
  return `${base}_${size}`;
}

/**
 * The kg one unit of the row weighs: 1 for KG, the row's own `kg_per_piece`
 * when set, otherwise the article's per-piece or per-bunch weight for the
 * row's size. 0 when no weight is known.
 */
export function kgPerRowUnit(record: TableRecord): number {
  const unit = planningRowUnit(record);
  if (unit === UnitEnum.KG) return 1;
  const rowOverride = parseFloat(String(record.kg_per_piece)) || 0;
  if (rowOverride) return rowOverride;
  const weightField = articleWeightField(unit, record.size);
  return weightField ? Number(record[weightField]) || 0 : 0;
}

/**
 * The price of one unit of the row: the row's own `price_per_unit` when set,
 * otherwise the article's net box price for the row's unit. 0 when no price
 * is known.
 */
export function pricePerRowUnit(
  record: TableRecord,
  article: ShareArticle | undefined,
): number {
  const rowOverride = parseFloat(String(record.price_per_unit)) || 0;
  if (rowOverride) return rowOverride;
  const priceField = articlePriceField(planningRowUnit(record));
  if (!article || !priceField) return 0;
  return parseFloat(String(article[priceField])) || 0;
}
