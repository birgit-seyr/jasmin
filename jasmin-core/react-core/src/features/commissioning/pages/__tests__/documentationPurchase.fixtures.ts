/**
 * The farm the purchase documentation tests run against: its storages,
 * articles and sellers, and the purchases of week 41 and week 39 of 2026 as
 * the week's summary lists them.
 */
import type {
  DocumentationSummaryRow,
  Reseller,
  ShareArticle,
  Storage,
} from "@shared/api/generated/models";

/** A summary row: the API row plus its ``storage_<id>`` flags. */
export type Row = DocumentationSummaryRow & Record<string, unknown>;
export type Payload = Record<string, unknown>;

export const COLD_STORE: Storage = { id: "storage-cold", name: "Cold store", is_active: true };
export const PACKING_SHED: Storage = { id: "storage-shed", name: "Packing shed", is_active: true };

const article = (name: string, unit: ShareArticle["default_movement_unit"]): ShareArticle => ({
  id: `article-${name.toLowerCase()}`, name, default_movement_unit: unit,
  is_active: true, is_purchased: true,
});
export const CARROTS = article("Carrots", "KG");
export const APPLES = article("Apples", "KG");
export const ONIONS = article("Onions", "KG");
export const PUMPKINS = article("Pumpkins", "PCS");
export const BEETROOT = article("Beetroot", "KG");
export const LEEKS = { ...article("Leeks", "PCS"), default_pieces_per_pu_purchase: "12.000" };
export const KALE = article("Kale", "BUNCH");

const seller = (id: string, companyName: string, controlNumber: string | null): Reseller => ({
  id, company_name: companyName, organic_control_number: controlNumber,
  is_seller: true, is_active_seller: true,
  address: "Field Lane 1", zip_code: "12345", city: "Greenville",
});
// Sunny Hill holds an organic certificate; Riverside doesn't.
export const SUNNY_HILL = seller("seller-sunny-hill", "Sunny Hill Farm", "DE-ECO-006-12345");
export const RIVERSIDE = seller("seller-riverside", "Riverside Growers", null);

export const soldBy = (reseller: Reseller) => ({
  seller: reseller.id ?? null,
  seller_name: reseller.company_name ?? null,
});

/** A purchase as the week's summary lists it, stored in ``storage``. */
export const purchaseRow = (product: ShareArticle, storage: Storage, fields: Partial<Row> = {}): Row => ({
  id: `purchase-${product.name.toLowerCase()}`, share_article: product.id ?? null,
  share_article_name: product.name, unit: product.default_movement_unit, size: "M", note: "",
  purchase_amount: null, theoretical_purchase_amount: 0, additional_theoretical_purchase_amount: 0,
  seller: null, seller_name: null, price_per_unit: null, organic_status: "conventional",
  // Summary fields this page doesn't show.
  theoretical_id: null, additional_id: null, amount_per_pu: null, theoretical_current_stock: null,
  forecast_plot_name: null, forecast_bed_number: null, forecast_note: null,
  harvesting_crate: null, harvesting_crate_name: null,
  ...Object.fromEntries(
    [COLD_STORE, PACKING_SHED].map((each) => [`storage_${each.id}`, each.id === storage.id]),
  ),
  ...fields,
});

// Bought, and expected by the planning: 10 planned plus 5 added by hand.
export const CARROTS_BOUGHT = purchaseRow(CARROTS, COLD_STORE, {
  purchase_amount: "12.50", price_per_unit: "1.85", ...soldBy(SUNNY_HILL),
  theoretical_purchase_amount: 10, additional_theoretical_purchase_amount: 5,
  organic_status: "organic", note: "Washed before delivery",
});
// Bought without any expectation.
export const APPLES_BOUGHT = purchaseRow(APPLES, COLD_STORE, {
  purchase_amount: "30.00", price_per_unit: "2.40", ...soldBy(RIVERSIDE),
});
// Expected by the planning, not bought yet: no seller, amount or price.
export const ONIONS_EXPECTED = purchaseRow(ONIONS, COLD_STORE, { theoretical_purchase_amount: 20 });
// Only an amount added by hand is expected.
export const PUMPKINS_EXPECTED = purchaseRow(PUMPKINS, COLD_STORE, {
  additional_theoretical_purchase_amount: 6,
});
// A leftover row with nothing expected and nothing bought.
export const BEETROOT_EMPTY = purchaseRow(BEETROOT, COLD_STORE);
export const LEEKS_IN_SHED = purchaseRow(LEEKS, PACKING_SHED, {
  purchase_amount: "40.00", price_per_unit: "0.90", ...soldBy(SUNNY_HILL),
});
// The expected onions, bought from Riverside: a row of its own beside the
// expected one, showing the same plan.
export const ONIONS_FROM_RIVERSIDE = purchaseRow(ONIONS, COLD_STORE, {
  id: "purchase-onions-riverside", purchase_amount: "20.00", theoretical_purchase_amount: 20,
  ...soldBy(RIVERSIDE),
});
export const CARROTS_WEEK_39 = purchaseRow(CARROTS, COLD_STORE, {
  id: "purchase-carrots-week-39", purchase_amount: "8.00", price_per_unit: "1.70",
  ...soldBy(SUNNY_HILL),
});
