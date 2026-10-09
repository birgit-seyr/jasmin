import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import type { Column } from "./columnTestHelpers";

export const sellers = [
  { value: "res-hof", label: "Biohof Mayr" },
  { value: "res-gross", label: "Großhandel Wien" },
];

export const finalColumn: Column = {
  title: "final",
  dataIndex: "is_finalized",
  key: "is_finalized",
};

export const shareArticleColumn: Column = {
  title: "article",
  dataIndex: "share_article_name",
  key: "share_article_name",
  inputType: "select",
};

export const amountUnitSizeColumns: Column[] = [
  {
    title: "unit",
    dataIndex: "unit",
    key: "unit",
    render: (value) => `unit:${String(value)}`,
  },
  { title: "size", dataIndex: "size", key: "size" },
];

export const washingCleaningColumns: Column[] = [
  { title: "wash", dataIndex: "washing", key: "washing" },
  { title: "clean", dataIndex: "cleaning", key: "cleaning" },
  {
    title: "storage",
    dataIndex: "comes_from_long_term_storage",
    key: "comes_from_long_term_storage",
  },
];

export const noteColumn: Column = {
  title: "note",
  dataIndex: "note",
  key: "note",
  inputType: "text",
  width: "16em",
};

export const deliveryDayColumns: Column[] = [
  { title: "Di", dataIndex: "day_day-tue", key: "day_day-tue" },
  { title: "Fr", dataIndex: "day_day-fri", key: "day_day-fri" },
];

/** A row scaffolded from a forecast of 40 kg, with 12.5 kg in stock. */
export const forecastRow: TableRecord = {
  key: "row-carrot",
  share_article_name: "Karotten",
  unit: "KG",
  size: "M",
  kg_per_piece: null,
  price_per_unit: "1.80",
  forecast: "fc-1",
  forecast_available_amount: "40.00",
  forecast_unit: "KG",
  forecast_note: "Feld 3",
  current_stock_begin_of_week: 12.5,
  current_stock_note: "gezählt",
  backup_share_article: "sa-beet",
};

/** A row holding only leftover stock. */
export const stockRow: TableRecord = {
  key: "row-leek",
  share_article_name: "Lauch",
  unit: "PCS",
  forecast: null,
  forecast_available_amount: null,
  forecast_unit: null,
  current_stock_begin_of_week: 30,
  backup_share_article: null,
};

/** A row the planner added by hand, with nothing behind it. */
export const plainRow: TableRecord = {
  key: "row-salad",
  share_article_name: "Salat",
  unit: "PCS",
  kg_per_piece: "0.350",
  price_per_unit: null,
  forecast: null,
  forecast_available_amount: null,
  forecast_unit: null,
  current_stock_begin_of_week: 0,
};
