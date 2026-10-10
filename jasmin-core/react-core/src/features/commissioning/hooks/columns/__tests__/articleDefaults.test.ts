/**
 * Share-article autofill: each page context pulls its own set of the
 * article's ``default_*`` fields into a row — harvest the harvest PU and
 * crate, purchase the purchase PU only, reseller the reseller PU, crate,
 * three price tiers and tax rate — and long-term planning nothing.
 */
import { describe, expect, it } from "vitest";

import type { ShareArticle } from "@shared/api/generated/models";

import { computeShareArticlePatch, computeUnitChangePatch } from "../articleDefaults";

const article = (fields: Record<string, unknown>) =>
  ({ description: "Crunchy", ...fields }) as unknown as ShareArticle;

const carrot = article({
  default_kg_per_pu_harvest: "12",
  default_pieces_per_pu_harvest: "40",
  default_bunches_per_pu_harvest: "20",
  default_kg_per_pu_purchase: "10",
  default_kg_per_pu_reseller: "5",
  default_bunches_per_pu_reseller: "15",
  default_crate_harvest: "crate-h",
  default_crate_reseller: "crate-r",
  net_price_for_orders_kg_1: "2.10",
  net_price_for_orders_kg_2: "2.00",
  net_price_for_orders_kg_3: "1.90",
  net_price_for_orders_bunch_1: "1.50",
  tax_rate: "7.00",
});

describe("computeShareArticlePatch", () => {
  it("fills the harvest PU and crate for a harvest row", () => {
    expect(computeShareArticlePatch("harvest", carrot, "kg")).toEqual({
      amount_per_pu: "12",
      harvesting_crate: "crate-h",
      harvesting_crate_name: "crate-h",
      description: "Crunchy",
    });
  });

  it("fills only the purchase PU for a purchase row", () => {
    expect(computeShareArticlePatch("purchase", carrot, "KG")).toEqual({
      amount_per_pu: "10",
      description: "Crunchy",
    });
  });

  it("fills PU, crate, three price tiers and tax rate for a reseller row", () => {
    expect(computeShareArticlePatch("reseller", carrot, "KG")).toEqual({
      amount_per_pu: "5",
      used_crate: "crate-r",
      used_crate_name: "crate-r",
      price_1: "2.10",
      price_2: "2.00",
      price_3: "1.90",
      tax_rate: "7.00",
      description: "Crunchy",
    });
  });

  it("reads the plural PU and the singular price field for bunches", () => {
    const patch = computeShareArticlePatch("reseller", carrot, "BUNCH");
    expect(patch.amount_per_pu).toBe("15");
    expect(patch).toMatchObject({ price_1: "1.50", price_2: 0, price_3: 0 });
  });

  it("maps PCS, in any case, to the pieces default", () => {
    expect(computeShareArticlePatch("harvest", carrot, "PCS").amount_per_pu).toBe("40");
    expect(computeShareArticlePatch("harvest", carrot, "pcs").amount_per_pu).toBe("40");
  });

  it("skips the PU and prices without a known unit", () => {
    for (const unit of [null, undefined, "", "LITRE", "PIECES", "L", "G"]) {
      const patch = computeShareArticlePatch("reseller", carrot, unit);
      expect(patch).not.toHaveProperty("amount_per_pu");
      expect(patch).not.toHaveProperty("price_1");
      expect(patch.used_crate).toBe("crate-r");
    }
  });

  it("keeps the caller's values where the article has no default", () => {
    const bare = article({ default_kg_per_pu_harvest: "", tax_rate: null, description: null });
    expect(computeShareArticlePatch("harvest", bare, "KG")).toEqual({ description: "" });
    expect(computeShareArticlePatch("reseller", bare, "KG")).not.toHaveProperty("tax_rate");
  });

  it("fills nothing for long-term planning", () => {
    expect(computeShareArticlePatch("longtermplanning", carrot, "KG")).toEqual({});
  });
});

describe("computeUnitChangePatch", () => {
  it("refreshes PU and prices but keeps the crate and description", () => {
    expect(computeUnitChangePatch("reseller", carrot, "BUNCH")).toEqual({
      amount_per_pu: "15",
      price_1: "1.50",
      price_2: 0,
      price_3: 0,
    });
  });

  it("refreshes only the PU on a harvest row", () => {
    expect(computeUnitChangePatch("harvest", carrot, "KG")).toEqual({ amount_per_pu: "12" });
  });

  it("changes nothing for long-term planning", () => {
    expect(computeUnitChangePatch("longtermplanning", carrot, "KG")).toEqual({});
  });
});
