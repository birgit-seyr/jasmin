import type { ReactNode } from "react";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import type { CrateOption } from "../../useCrates";

export const unitOptions = [
  { value: "KG", label: "kg" },
  { value: "PCS", label: "Stk." },
  { value: "BUNCH", label: "Bund" },
];

export const crates = [
  { value: null, label: "-" },
  { value: "crate-e2", label: "E2" },
] as unknown as CrateOption[];

export const shareOptions = [
  { value: "HARVEST_SHARE", label: "Harvest share" },
  { value: "HARVEST_SHARE_FRUIT", label: "Fruit share" },
];

export const isActiveColumn = {
  title: "active",
  dataIndex: "is_active",
  key: "is_active",
  inputType: "checkbox",
};

export const priceModalColumn = {
  title: "prices",
  dataIndex: "prices",
  key: "prices",
};

type NumberRenderer = (
  decimals: number,
) => (value: number, record: TableRecord) => ReactNode;

const passThroughNumber: NumberRenderer = (decimals) => (value) =>
  value == null ? null : `${value}@${decimals}`;

export const baseArgs = {
  isActiveColumn,
  priceModalColumn: null as Record<string, unknown> | null,
  unitOptions,
  crates,
  visibleShareOptions: shareOptions,
  activeFilter: "all",
  sells_to_resellers: true,
  has_markets: true,
  number_packing_stations: 2,
  packingBulk: false,
  renderHarvestNumber: passThroughNumber,
  renderPurchaseNumber: passThroughNumber,
};

/** A saved, harvested (not purchased) article as the list returns it. */
export const harvestedArticle: TableRecord = {
  key: "sa-carrot",
  id: "sa-carrot",
  name: "Karotten",
  is_purchased: false,
  can_be_deleted: false,
  default_movement_unit: "KG",
  default_commissioning_unit: "BUNCH",
  default_crate_harvest: "crate-e2",
  default_crate_harvest_name: "E2",
  default_kg_per_pu_harvest: "12.500",
};

/** A saved, purchased article. */
export const purchasedArticle: TableRecord = {
  key: "sa-lemon",
  id: "sa-lemon",
  name: "Zitronen (Zukauf)",
  is_purchased: true,
  can_be_deleted: true,
  default_movement_unit: "PCS",
  default_crate_harvest: "crate-e2",
  default_crate_harvest_name: "E2",
  default_kg_per_pu_purchase: "10.000",
};

/** The row the table adds before its first save. */
export const newArticle: TableRecord = { key: -1 };
