/**
 * Share-article autofill: pick which set of ``default_*`` fields to
 * pull from a chosen ShareArticle into a row's form. The right set
 * depends on the page's job:
 *
 *   - HarvestingList / PlanningHarvestShares enter HARVEST data →
 *     ``default_<unit>_per_pu_harvest`` + ``default_crate_harvest``.
 *   - PurchaseList enters BUYING data →
 *     ``default_<unit>_per_pu_purchase`` (no crate field exists).
 *   - Offers / Orders / InvoiceModal enter RESELLER ORDER data →
 *     ``default_<unit>_per_pu_reseller`` + ``default_crate_reseller``
 *     + the 3 price tiers ``net_price_for_orders_<unit>_{1,2,3}``
 *     so downstream tier calculation can pick the right price for
 *     the chosen quantity.
 *
 * Field-name source of truth: ``apps/commissioning/models/basics.py``.
 *
 * Quirk: the per-PU defaults pluralise BUNCH → bunches
 * (``default_bunches_per_pu_*``), but the price fields keep it
 * singular (``net_price_for_orders_bunch_*``). The dispatch table
 * enumerates both spellings so the inconsistency stays in one place.
 */

import type { ShareArticle } from "@shared/api/generated/models";

export type ArticleDefaults =
  | "harvest"
  | "purchase"
  | "reseller"
  // Long-term default-content planning: seed ONLY the row's ``unit`` (from the
  // article's ``default_movement_unit``, done by the caller) and autofill
  // nothing else. Avoids leaking crate / ``amount_per_pu`` fields into the
  // default-content payload, where the backend parses every ``amount_*`` key
  // as a share_type_variation id.
  | "longtermplanning";

/** Unit values stored on rows. We normalise to uppercase for lookups. */
type UnitKey = "KG" | "PCS" | "PIECES" | "BUNCH";

interface CrateBinding {
  /** ShareArticle field carrying the crate FK id. */
  sourceValue: string;
  /**
   * Form field that should receive the FK id. Both the ``targetValue``
   * key AND the column's ``dataIndex`` (the "_name" sibling) are set
   * to the same id — that's the convention the EditableTable foreignKey
   * selects use. The options list is shaped ``{ value: id, label: name }``
   * so the select resolves the id to the right label on display.
   */
  targetValue: string;
  /** Form field on the column's ``dataIndex`` (the "_name" sibling). */
  targetDisplay: string;
}

interface PriceBinding {
  /** How many price tiers to fill (1 or 3). */
  tiers: number;
  /** ShareArticle field name for a (unit, tier) pair. */
  source: (unit: UnitKey, tier: number) => string;
  /** Form field that should receive the value for the given tier. */
  target: (tier: number) => string;
}

interface TaxRateBinding {
  /** ShareArticle field carrying the tax rate (%). */
  source: string;
  /** Form field that should receive the tax rate. */
  target: string;
}

interface ArticleDefaultsDef {
  /** ShareArticle field carrying the amount-per-PU default for each unit. */
  amountPerPu: Record<UnitKey, string>;
  /** Form field that should receive the amount-per-PU value. */
  amountPerPuFormKey: string;
  /** Crate fields, if this context has a crate concept. */
  crate?: CrateBinding;
  /** Price-tier fields, if this context fills prices. */
  prices?: PriceBinding;
  /**
   * Tax-rate field, if this context's table has a ``tax_rate`` column.
   * Filled on share-article change (not on unit change — ``tax_rate``
   * lives on ``ShareArticleNetPrice`` and is unit-independent).
   */
  taxRate?: TaxRateBinding;
}

const PER_PU_HARVEST: Record<UnitKey, string> = {
  KG: "default_kg_per_pu_harvest",
  PCS: "default_pieces_per_pu_harvest",
  PIECES: "default_pieces_per_pu_harvest",
  BUNCH: "default_bunches_per_pu_harvest",
};

const PER_PU_PURCHASE: Record<UnitKey, string> = {
  KG: "default_kg_per_pu_purchase",
  PCS: "default_pieces_per_pu_purchase",
  PIECES: "default_pieces_per_pu_purchase",
  BUNCH: "default_bunches_per_pu_purchase",
};

const PER_PU_RESELLER: Record<UnitKey, string> = {
  KG: "default_kg_per_pu_reseller",
  PCS: "default_pieces_per_pu_reseller",
  PIECES: "default_pieces_per_pu_reseller",
  BUNCH: "default_bunches_per_pu_reseller",
};

const RESELLER_ORDER_PRICE_SUFFIX: Record<UnitKey, string> = {
  KG: "kg",
  PCS: "pieces",
  PIECES: "pieces",
  BUNCH: "bunch",
};

// ``longtermplanning`` is intentionally absent — it autofills nothing, handled
// by an early return in the functions below.
const CONTEXTS: Record<
  Exclude<ArticleDefaults, "longtermplanning">,
  ArticleDefaultsDef
> = {
  harvest: {
    amountPerPu: PER_PU_HARVEST,
    amountPerPuFormKey: "amount_per_pu",
    crate: {
      sourceValue: "default_crate_harvest",
      targetValue: "harvesting_crate",
      targetDisplay: "harvesting_crate_name",
    },
  },
  purchase: {
    amountPerPu: PER_PU_PURCHASE,
    amountPerPuFormKey: "amount_per_pu",
  },
  reseller: {
    amountPerPu: PER_PU_RESELLER,
    amountPerPuFormKey: "amount_per_pu",
    crate: {
      sourceValue: "default_crate_reseller",
      targetValue: "used_crate",
      targetDisplay: "used_crate_name",
    },
    prices: {
      tiers: 3,
      source: (unit, tier) =>
        `net_price_for_orders_${RESELLER_ORDER_PRICE_SUFFIX[unit] ?? "kg"}_${tier}`,
      target: (tier) => `price_${tier}`,
    },
    // Reseller tables (Offer / Order / Invoice / DeliveryNote line items)
    // all carry ``tax_rate`` on the model. Harvest / purchase pages do not.
    taxRate: {
      source: "tax_rate",
      target: "tax_rate",
    },
  },
};

/** Read a field from a ShareArticle dynamically (typed loosely on purpose). */
const readField = (article: ShareArticle, field: string): unknown =>
  (article as unknown as Record<string, unknown>)[field];

/** Normalise whatever unit value the form carries to one of our keys. */
const normaliseUnit = (raw: unknown): UnitKey | null => {
  if (typeof raw !== "string" || !raw) return null;
  const up = raw.toUpperCase();
  if (up in PER_PU_HARVEST) return up as UnitKey;
  return null;
};

function buildAmountPatch(
  def: ArticleDefaultsDef,
  article: ShareArticle,
  unitKey: UnitKey | null,
): Record<string, unknown> {
  if (!unitKey) return {};
  const field = def.amountPerPu[unitKey];
  if (!field) return {};
  const value = readField(article, field);
  if (value == null || value === "") return {};
  return { [def.amountPerPuFormKey]: value };
}

function buildPricePatch(
  def: ArticleDefaultsDef,
  article: ShareArticle,
  unitKey: UnitKey | null,
): Record<string, unknown> {
  if (!def.prices || !unitKey) return {};
  const patch: Record<string, unknown> = {};
  for (let tier = 1; tier <= def.prices.tiers; tier++) {
    const value = readField(article, def.prices.source(unitKey, tier));
    patch[def.prices.target(tier)] = value ?? 0;
  }
  return patch;
}

function buildCratePatch(
  def: ArticleDefaultsDef,
  article: ShareArticle,
): Record<string, unknown> {
  if (!def.crate) return {};
  const id = readField(article, def.crate.sourceValue);
  if (!id) return {};
  // BOTH keys get the same id — that's the convention the EditableTable
  // foreignKey select expects. The select's options are
  // ``{ value: id, label: name }`` and the form-bound dataIndex is the
  // "_name" sibling; setting the *name* key to the id lets the select
  // match the option and render the right label. Setting it to the raw
  // name string would not match any option and the cell stays empty.
  return {
    [def.crate.targetValue]: id,
    [def.crate.targetDisplay]: id,
  };
}

function buildTaxRatePatch(
  def: ArticleDefaultsDef,
  article: ShareArticle,
): Record<string, unknown> {
  if (!def.taxRate) return {};
  const value = readField(article, def.taxRate.source);
  // Only overwrite when the article actually carries a tax rate. An
  // article without a current ``ShareArticleNetPrice`` row leaves
  // ``tax_rate`` as null — in that case keep whatever the caller
  // already seeded (typically the ``default_tax_rate_articles`` tenant
  // setting from ``customEdit``).
  if (value == null || value === "") return {};
  return { [def.taxRate.target]: value };
}

/**
 * Patch to apply on share-article selection. Fills everything the
 * context knows about: amount-per-PU (from the article's default unit
 * if no unit yet), crate, prices, plus the article's ``description``.
 * Caller still owns ``unit`` itself (we leave it to the page to decide
 * whether to seed unit from ``default_movement_unit`` since that has
 * other side effects).
 */
export function computeShareArticlePatch(
  ctx: ArticleDefaults,
  article: ShareArticle,
  unit: string | null | undefined,
): Record<string, unknown> {
  if (ctx === "longtermplanning") return {};
  const def = CONTEXTS[ctx];
  const unitKey = normaliseUnit(unit);
  return {
    ...buildAmountPatch(def, article, unitKey),
    ...buildCratePatch(def, article),
    ...buildPricePatch(def, article, unitKey),
    ...buildTaxRatePatch(def, article),
    description: article.description ?? "",
  };
}

/**
 * Patch to apply on unit-change for a row that already has a
 * share_article. Refreshes amount-per-PU and price tiers but does NOT
 * touch the crate (so the user's prior crate pick is preserved) or
 * the description.
 */
export function computeUnitChangePatch(
  ctx: ArticleDefaults,
  article: ShareArticle,
  newUnit: string | null | undefined,
): Record<string, unknown> {
  if (ctx === "longtermplanning") return {};
  const def = CONTEXTS[ctx];
  const unitKey = normaliseUnit(newUnit);
  return {
    ...buildAmountPatch(def, article, unitKey),
    ...buildPricePatch(def, article, unitKey),
  };
}
