"""What a customer may order through their own order page.

A customer, a login without an office, admin or management role, orders for
the reseller linked to it. Their order page lists the finalized offers of the
reseller's offer group for the week it shows and saves an amount per offer,
and the server prices each line from its offer
(``tier_price.set_customer_line_price``). It shows the lines office staff added
without an offer read-only, and it never sends the order's days. These rules
hold a customer's request to what that page sends, so a hand-built one can't
order on better terms or move the order's work. Office staff aren't held to
them: their order page offers drafts too, and they price lines and set the
order's days themselves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.shared.money import to_decimal

from ..errors import (
    OrderContentAmountNegative,
    OrderContentOfferNotFinalized,
    OrderContentOfferNotInOfferGroup,
    OrderContentOfferRequired,
    OrderContentOfferWeekMismatch,
)
from .order_days import ORDER_DAY_FIELDS

if TYPE_CHECKING:
    from ..models import OrderContent, Reseller


def assert_customer_orderable_offer(line: dict[str, Any], reseller: Reseller) -> None:
    """Refuse a customer's new order ``line`` unless it orders an offer their
    order page lists for the order's week.

    That is an offer, not a free ``share_article``, which would skip the stock
    check and the offer group's offer set. The offer is of the reseller's offer
    group, finalized, and of the order's year and week: the server prices the
    line from it and takes the line's stock from it.
    """
    offer = line.get("offer")
    if offer is None or line.get("share_article") is not None:
        raise OrderContentOfferRequired("Customers may only order offers.")
    offer_group_id = reseller.offer_group_id
    if offer_group_id is None or offer.offer_group_id != offer_group_id:
        raise OrderContentOfferNotInOfferGroup(
            "This offer is not part of your offer group."
        )
    if not offer.is_finalized:
        raise OrderContentOfferNotFinalized(
            "This offer is not finalized yet.", field="offer"
        )
    order_week = (line.get("year"), line.get("delivery_week"))
    if (offer.year, offer.delivery_week) != order_week:
        raise OrderContentOfferWeekMismatch(
            "This offer is for another week than the order.", field="offer"
        )


def drop_customer_order_days(line: dict[str, Any]) -> None:
    """Drop the order's days from a customer's new order ``line``.

    The order's harvesting, washing, cleaning and packing days schedule the
    farm's work for it, and they and its ordering deadline are office staff's
    to set. The order page sends none, so a sent one is dropped rather than
    refused and no client's order fails over it: a new order takes the delivery
    day's defaults, and an existing one keeps its days
    (``order_days.apply_order_days``).
    """
    for field in ORDER_DAY_FIELDS:
        line.pop(field, None)


def assert_customer_amount_not_negative(line: dict[str, Any]) -> None:
    """Refuse a customer's write of an order ``line`` that sets a negative
    amount. The line keeps a positive price, so it would reach the delivery
    note and the invoice as a credit, and its PU would go back to the offer's
    stock. A write without an amount keeps the stored one."""
    amount = line.get("amount")
    if amount is not None and amount < 0:
        raise OrderContentAmountNegative(
            "The ordered amount cannot be negative.", field="amount"
        )


# What a customer's write may not change on a stored line without an offer: its
# amount and every other field the update writes
# (``order_content_service._UPDATABLE_ORDER_CONTENT_FIELDS``) but its offer or
# article, price, rabatt and tax rate, which have rules of their own.
_READ_ONLY_FIELDS_WITHOUT_OFFER = (
    "amount",
    "description",
    "unit",
    "size",
    "sort",
    "note",
    "washing",
    "cleaning",
    "comes_from_long_term_storage",
)


def assert_customer_line_write_allowed(
    line: dict[str, Any], instance: OrderContent | None
) -> None:
    """Refuse a customer's write of an order ``line`` their order page can't
    make: a negative amount (``assert_customer_amount_not_negative``), or a
    change to ``instance``, the stored line (``None`` for a new one), when it
    has no offer.

    Office staff add a line without an offer at their own price and rabatt,
    with no stock to check its amount against. The delivery note and the
    invoice take its unit, size, sort and description from the line itself, and
    the goods flow plans its harvest, washing and storage from it. The page
    shows it read-only: it is theirs to change. Re-sending a stored value is no
    change, and neither is one empty value for another: an empty amount counts
    as 0, as the update stores it, and an empty text or flag as none, as every
    reader of the line takes it.
    """
    assert_customer_amount_not_negative(line)
    if instance is None or instance.offer_id is not None:
        return
    for field in _READ_ONLY_FIELDS_WITHOUT_OFFER:
        if field in line and _changes(field, line[field], getattr(instance, field)):
            raise OrderContentOfferRequired(
                "Only office staff may change a line without an offer.",
                field=field,
            )


def _changes(field: str, sent: Any, stored: Any) -> bool:
    if field == "amount":
        return to_decimal(sent) != to_decimal(stored)
    return (sent or None) != (stored or None)
