import type {
  Offer,
  OrderContentListItem,
} from "@shared/api/generated/models";

/**
 * Row shape for the customer offers table.
 *
 * Base is the backend list item (real order lines merged with unused-offer
 * placeholder rows); the page adds the derived fields when the row carries an
 * actual order line. On these rows `id` holds the OFFER id (the table rowKey)
 * while `order_content_id` keeps the order-content id needed for PATCH.
 * `ordered_amount_num` is the ordered PU count coerced to a number — the
 * backend field `ordered_amount` stays the raw decimal string.
 */
export type CustomerOrderRow = OrderContentListItem & {
  order_content_id?: string | null;
  order_price?: number | null;
  ordered_amount_num?: number | null;
};

/**
 * Fallback row built directly from a finalized `Offer` when the
 * order-contents response has no rows yet. Mirrors the derived fields of
 * `CustomerOrderRow` so both shapes flow through the same columns and cells.
 */
export type OfferRow = Offer & {
  id: string;
  order_content_id: null;
  order_price: null;
  ordered_amount_num: null;
  order_is_finalized: false;
};

/** What the offers table actually renders. */
export type CustomerOrderTableRow = CustomerOrderRow | OfferRow;

/**
 * Offer-less order line (office-added directly) shown in the separate
 * "other articles" table; `id` is narrowed because these are always real
 * persisted order-content rows.
 */
export type OtherArticleRow = OrderContentListItem & { id: string };
