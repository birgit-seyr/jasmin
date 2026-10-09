import type { TableRecord } from "@shared/tables/BasicEditableTable/types";

export const crates = [
  { value: null, label: "-" },
  { value: "crate-e2", label: "E2" },
];

/** A harvesting-list row as useHarvestingListData hands it to the table. */
export const carrotRow: TableRecord = {
  key: "hl-carrot",
  id: "hl-carrot",
  share_article: "sa-carrot",
  share_article_name: "Karotten",
  unit: "KG",
  size: "L",
  theoretical_harvest_amount_share_content: "12.5",
  theoretical_harvest_amount_order_content: 0,
  computed_still_in_stock_share_content: 3,
  computed_still_in_stock_order_content: null,
  computed_to_harvest_share_content: 9.5,
  computed_to_harvest_order_content: 4,
  amount_share_content: 2,
  amount_order_content: null,
  additional_theoretical_harvest_amount_share_content: "2.25",
  additional_theoretical_harvest_amount_order_content: null,
  computed_total_amount_text_share_content: "12,00 kg",
  computed_amount_pu_text_share_content: "1 PU",
  computed_amount_combined_share_content: "12,00 kg - 1 PU",
  computed_total_amount_text_order_content: "4,00 kg",
  computed_amount_pu_text_order_content: "",
  computed_amount_combined_order_content: "4,00 kg",
  computed_amount_per_pu_text: "12,00 kg/PU",
  computed_article_with_size: "Karotten (groß)",
  harvesting_crate: "crate-e2",
  harvesting_crate_name: "E2",
  note: "vom Feld 3",
  computed_note_line: "vom Feld 3",
  computed_plot_line: "Feld 3, Beet 2",
};

/** A bunch row with no PU, note or plot. */
export const radishRow: TableRecord = {
  key: "hl-radish",
  id: "hl-radish",
  share_article: "sa-radish",
  share_article_name: "Radieschen",
  unit: "BUNCH",
  size: "M",
  theoretical_harvest_amount_share_content: 30,
  computed_amount_per_pu_text: "",
  computed_note_line: "",
  computed_plot_line: "",
};

/** The row the table adds before its first save. */
export const newRow: TableRecord = { key: -1 };
