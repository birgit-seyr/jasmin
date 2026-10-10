/**
 * The purchase list's rows: the selected week's rows with an amount, each with
 * next week's theoretical amount of its article line, then one row for every
 * other line next week needs — the week's own amount-less row when it has one,
 * else a next-week-only row whose save cannot reach next week's entry.
 */
import { describe, expect, it } from "vitest";

import type { DocumentationSummaryRecord } from "@features/commissioning/hooks/useDocumentationSummaryPage";

import { isNextWeekOnlyRowKey, mergePurchaseListRows } from "../purchaseListWeeks";

const row = (overrides: Partial<DocumentationSummaryRecord>): DocumentationSummaryRecord => ({
  key: overrides.id ?? "row",
  id: "row",
  share_article: "carrot",
  share_article_name: "Carrots",
  unit: "KG",
  size: "M",
  note: "",
  theoretical_id: null,
  additional_id: null,
  forecast_plot_name: null,
  forecast_bed_number: null,
  forecast_note: null,
  theoretical_current_stock: null,
  amount_per_pu: "10",
  harvesting_crate: null,
  harvesting_crate_name: null,
  seller: "seller-1",
  seller_name: "Wholesale",
  price_per_unit: null,
  theoretical_purchase_amount: 0,
  additional_theoretical_purchase_amount: 0,
  purchase_amount: null,
  ...overrides,
});

describe("mergePurchaseListRows", () => {
  it("lists only the week's rows with an amount when next week isn't included", () => {
    const listed = row({ id: "a", theoretical_purchase_amount: 5 });
    const bought = row({ id: "b", share_article: "leek", purchase_amount: "2" });
    const empty = row({ id: "c", share_article: "kale" });

    const rows = mergePurchaseListRows([listed, bought, empty], undefined);

    expect(rows.map((r) => r.id)).toEqual(["a", "b"]);
    expect(rows.every((r) => r.next_week_theoretical === 0)).toBe(true);
  });

  it("copies the rows instead of changing the cached ones", () => {
    const listed = row({ id: "a", theoretical_purchase_amount: 5 });
    const [merged] = mergePurchaseListRows([listed], []);
    expect(merged).not.toBe(listed);
    expect(listed.next_week_theoretical).toBeUndefined();
  });

  it("gives each listed row next week's theoretical amount of its line", () => {
    const current = row({ id: "a", theoretical_purchase_amount: 5 });
    const nextSameLine = row({ id: "n1", theoretical_purchase_amount: 8 });
    const nextOtherSize = row({ id: "n2", size: "L", theoretical_purchase_amount: 0 });

    const rows = mergePurchaseListRows([current], [nextSameLine, nextOtherSize]);

    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ id: "a", next_week_theoretical: 8 });
  });

  it("adds a next-week-only row for a line the week lacks", () => {
    const next = row({
      id: "n1",
      share_article: "leek",
      theoretical_id: "theo-next",
      additional_id: "add-next",
      theoretical_purchase_amount: 4,
      additional_theoretical_purchase_amount: 1,
      purchase_amount: "3",
      note: "next week's note",
    });

    const [added] = mergePurchaseListRows([], [next]);

    expect(added.id).toBe("next_week_only:leek_KG_M");
    expect(isNextWeekOnlyRowKey(added.id)).toBe(true);
    expect(added).toMatchObject({
      share_article: "leek",
      seller: "seller-1",
      amount_per_pu: "10",
      theoretical_id: null,
      additional_id: null,
      theoretical_purchase_amount: 0,
      additional_theoretical_purchase_amount: 0,
      purchase_amount: null,
      note: "",
      next_week_theoretical: 4,
    });
  });

  it("shows the week's own amount-less row for a line next week needs", () => {
    const currentEmpty = row({ id: "own", share_article: "leek" });
    const next = row({ id: "n1", share_article: "leek", theoretical_purchase_amount: 4 });

    const rows = mergePurchaseListRows([currentEmpty], [next]);

    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ id: "own", next_week_theoretical: 4 });
  });

  it("skips next week's lines without a theoretical amount or already listed", () => {
    const current = row({ id: "a", theoretical_purchase_amount: 5 });
    const nextListed = row({ id: "n1", theoretical_purchase_amount: 6 });
    const nextNothing = row({ id: "n2", share_article: "kale", theoretical_purchase_amount: 0 });

    const rows = mergePurchaseListRows([current], [nextListed, nextNothing]);

    expect(rows.map((r) => r.id)).toEqual(["a"]);
  });

  it("treats a missing current week as empty", () => {
    const next = row({ id: "n1", theoretical_purchase_amount: 2 });
    expect(mergePurchaseListRows(undefined, [next])).toHaveLength(1);
    expect(mergePurchaseListRows(undefined, undefined)).toEqual([]);
  });
});

describe("isNextWeekOnlyRowKey", () => {
  it("recognises only the next-week-only prefix on a string key", () => {
    expect(isNextWeekOnlyRowKey("next_week_only:leek_KG_M")).toBe(true);
    expect(isNextWeekOnlyRowKey("AB12cdEFgh34")).toBe(false);
    expect(isNextWeekOnlyRowKey(-1)).toBe(false);
    expect(isNextWeekOnlyRowKey(undefined)).toBe(false);
  });
});
