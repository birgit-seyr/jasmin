"""What a customer may order through their own order page.

A customer, a login without an office, admin or management role, orders for
the reseller linked to it. Their order page lists the finalized offers of the
reseller's offer group for the week it shows and saves an amount per offer,
and the server prices each line from its offer
(``tier_price.set_customer_line_price``). It shows the lines office staff added
that the customer couldn't have ordered read-only, closes a week once it is
past or the delivery day's ordering deadline has passed, and never sends the
order's days. These rules hold a customer's request to what that page sends, so
a hand-built one can't order on better terms, late, or move the order's work.
Office staff aren't held to them: their order page offers drafts too, and they
price lines and set the order's days themselves.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

from django.utils import timezone
from isoweek import Week

from apps.shared.money import to_decimal
from core.errors import JasminError

from ..errors import (
    OrderContentAmountNegative,
    OrderContentItemChangeForbidden,
    OrderContentOfferNotFinalized,
    OrderContentOfferNotInOfferGroup,
    OrderContentOfferRequired,
    OrderContentOfferWeekMismatch,
    OrderContentOfficeOnly,
    OrderDayNotOffered,
    OrderingDeadlinePassed,
    PastWeekError,
)
from ..models import OrdersDeliveryDay
from .order_days import ORDER_DAY_FIELDS

if TYPE_CHECKING:
    from ..models import Offer, OrderContent, Reseller


def restrict_customer_new_line(line: dict[str, Any], reseller: Reseller) -> None:
    """Hold a customer's new order ``line`` for ``reseller`` to what their
    order page sends: an offer it lists, for a week and day it still takes
    orders for, without the order's days or the fields the line takes from its
    offer."""
    assert_customer_orderable_offer(line, reseller)
    assert_customer_ordering_open(
        line["year"], line["delivery_week"], line["day_number"], new_line=True
    )
    drop_customer_order_days(line)
    drop_customer_offer_fields(line)


def restrict_customer_line_change(line: dict[str, Any], instance: OrderContent) -> None:
    """Hold a customer's change of their stored order line ``instance`` to
    ``line`` to what their order page sends: it comes while the page still
    takes orders for the line's week and day, and keeps the line's offer and
    article. What else it may change is ``assert_customer_line_write_allowed``'s
    to say."""
    _assert_ordering_open_for(instance)
    _assert_customer_item_unchanged(line, instance)


def restrict_customer_line_delete(instance: OrderContent) -> None:
    """Hold a customer's delete of their stored order line ``instance`` to
    what their order page offers: it comes while the page still takes orders
    for the line's week and day, and leaves office lines alone
    (``assert_customer_line_deletable``)."""
    _assert_ordering_open_for(instance)
    assert_customer_line_deletable(instance)


def _assert_ordering_open_for(instance: OrderContent) -> None:
    order = instance.order
    assert_customer_ordering_open(
        order.year, order.delivery_week, order.day_number, new_line=False
    )


def _assert_customer_item_unchanged(
    line: dict[str, Any], instance: OrderContent
) -> None:
    """Refuse a re-point of the stored line ``instance`` at another offer or
    article: its stock was reserved on the current offer, and the
    orderable-offer check ran against that offer when the line was created.
    Re-sending the current value is no change."""
    current_ids = {
        "offer": instance.offer_id,
        "share_article": instance.share_article_id,
    }
    for field, current_id in current_ids.items():
        if field in line and getattr(line[field], "pk", None) != current_id:
            raise OrderContentItemChangeForbidden(
                "An order line's offer can't be changed, and only office "
                "staff may change its article."
            )


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
    refusal = _offer_refusal(
        offer, reseller, line.get("year"), line.get("delivery_week")
    )
    if refusal is not None:
        raise refusal


def _offer_refusal(
    offer: Offer, reseller: Reseller, year: int | None, delivery_week: int | None
) -> JasminError | None:
    """Why a customer of ``reseller`` may not order ``offer`` for ``year``'s
    ``delivery_week``, or ``None`` when their order page lists it there."""
    offer_group_id = reseller.offer_group_id
    if offer_group_id is None or offer.offer_group_id != offer_group_id:
        return OrderContentOfferNotInOfferGroup(
            "This offer is not part of your offer group."
        )
    if not offer.is_finalized:
        return OrderContentOfferNotFinalized(
            "This offer is not finalized yet.", field="offer"
        )
    if (offer.year, offer.delivery_week) != (year, delivery_week):
        return OrderContentOfferWeekMismatch(
            "This offer is for another week than the order.", field="offer"
        )
    return None


def assert_customer_ordering_open(
    year: int, delivery_week: int, day_number: int | None, *, new_line: bool
) -> None:
    """Refuse a customer's write to their order for ``day_number`` of
    ``year``'s ``delivery_week`` once their order page shows it closed: the
    week lies before the current one, or the delivery day's ordering deadline
    (``ordering_deadline``) has passed. A ``new_line`` also needs a day the
    page's day picker lists: one with an order delivery day
    (``OrdersDeliveryDay``), or, while the farm has set up none, any day from
    Monday to Saturday, which then has no deadline. An order without a day has
    no deadline either."""
    if Week(year, delivery_week) < Week.withdate(timezone.localdate()):
        raise PastWeekError(
            f"Week {delivery_week} of {year} is past.",
            details={"year": year, "delivery_week": delivery_week},
        )
    order_day = (
        OrdersDeliveryDay.objects.filter(day_number=day_number).first()
        if day_number is not None
        else None
    )
    if order_day is None:
        if new_line and not _picked_without_order_days(day_number):
            raise OrderDayNotOffered(
                f"No orders are delivered on day {day_number}.",
                field="day_number",
                details={"day_number": day_number},
            )
        return
    deadline = ordering_deadline(order_day, year, delivery_week)
    if deadline is not None and timezone.now() > deadline:
        raise OrderingDeadlinePassed(
            "The ordering deadline of this delivery day has passed.",
            details={"deadline": deadline.isoformat()},
        )


# The days the customer page's day picker offers while the farm has set up no
# order delivery day: Monday to Saturday.
_DAYS_WITHOUT_ORDER_DAYS = frozenset(range(6))


def _picked_without_order_days(day_number: int | None) -> bool:
    return (
        day_number in _DAYS_WITHOUT_ORDER_DAYS
        and not OrdersDeliveryDay.objects.exists()
    )


def ordering_deadline(
    order_day: OrdersDeliveryDay, year: int, delivery_week: int
) -> dt.datetime | None:
    """When customers' ordering for ``order_day`` in ``year``'s
    ``delivery_week`` closes, as their order page works it out
    (``useOrderingDeadline``): the ``default_last_possible_ordering_day`` of
    that week, at the minute of ``default_last_possible_ordering_time`` or else
    at the day's end; ``None`` while the day sets no deadline. An order's own
    ``last_possible_ordering_day`` doesn't move it, as the page doesn't read
    it."""
    last_day = order_day.default_last_possible_ordering_day
    if last_day is None:
        return None
    day = Week(year, delivery_week).monday() + dt.timedelta(days=last_day)
    last_time = order_day.default_last_possible_ordering_time
    at = last_time.replace(second=0, microsecond=0) if last_time else dt.time.max
    return timezone.make_aware(dt.datetime.combine(day, at))


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


# The fields a line keeps as its offer gives them, and the update writes
# (``order_content_service._UPDATABLE_ORDER_CONTENT_FIELDS``): the goods flow
# plans the line's harvest, washing, cleaning and storage moves from them. A
# customer's new line takes them from its offer, and a customer's write may
# not change them on a stored one.
_OFFER_FIELDS = (
    "description",
    "unit",
    "size",
    "sort",
    "washing",
    "cleaning",
    "comes_from_long_term_storage",
)

# What a customer's write may not change on a line office staff added that the
# customer couldn't have ordered (``is_office_line``): its amount and note too.
# Its offer or article, price, rabatt and tax rate have rules of their own.
_OFFICE_LINE_FIELDS = ("amount", "note", *_OFFER_FIELDS)


def drop_customer_offer_fields(line: dict[str, Any]) -> None:
    """Drop the fields a customer's new order ``line`` takes from its offer
    (``_OFFER_FIELDS``); the order line service fills each from the offer. The
    order page sends the offer's unit, so a sent field is dropped rather than
    refused."""
    for field in _OFFER_FIELDS:
        line.pop(field, None)


def is_office_line(instance: OrderContent) -> bool:
    """Whether the stored line ``instance`` is one office staff added that the
    customer of its order's reseller couldn't have ordered: without an offer, or
    on an offer their order page doesn't list for the order's week. The page
    shows it read-only."""
    offer = instance.offer
    if offer is None:
        return True
    order = instance.order
    refusal = _offer_refusal(offer, order.reseller, order.year, order.delivery_week)
    return refusal is not None


def assert_customer_line_write_allowed(
    line: dict[str, Any], instance: OrderContent | None
) -> None:
    """Refuse a customer's write of an order ``line`` their order page can't
    make: a negative amount (``assert_customer_amount_not_negative``), or a
    change to ``instance``, the stored line (``None`` for a new one), of a field
    the line takes from its offer, or of any field on an office line
    (``is_office_line``).

    Office staff add a line at their own price and rabatt, with no offer stock
    to check its amount against or none the customer may order from. The
    delivery note and the invoice take a line without an offer's unit, size,
    sort and description from the line itself, and the goods flow plans every
    line's harvest, washing and storage from it. Re-sending a stored value is
    no change, and neither is one empty value for another: an empty amount
    counts as 0, as the update stores it, and an empty text or flag as none, as
    every reader of the line takes it.
    """
    assert_customer_amount_not_negative(line)
    if instance is None:
        return
    office_line = is_office_line(instance)
    for field in _OFFICE_LINE_FIELDS if office_line else _OFFER_FIELDS:
        if field in line and _changes(field, line[field], getattr(instance, field)):
            raise OrderContentOfficeOnly(
                "Only office staff may change this.", field=field
            )


def assert_customer_line_deletable(instance: OrderContent) -> None:
    """Refuse a customer's delete of the stored line ``instance`` when it is an
    office line (``is_office_line``), which their order page shows
    read-only."""
    if is_office_line(instance):
        raise OrderContentOfficeOnly("Only office staff may delete this line.")


def _changes(field: str, sent: Any, stored: Any) -> bool:
    if field == "amount":
        return to_decimal(sent) != to_decimal(stored)
    return (sent or None) != (stored or None)
