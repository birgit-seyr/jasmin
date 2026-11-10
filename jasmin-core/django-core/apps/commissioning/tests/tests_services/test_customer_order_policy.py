"""What a customer may order: the offer a new line takes, the order's days and
the offer's fields it never sets, and what any write of a line sets: no
negative amount, no change to what the line takes from its offer, and no change
to or delete of a line office staff added that the customer couldn't have
ordered. When ordering closes is the delivery day's deadline in the order's
week.

The rules read only the request body and the own fields of the offer, the
reseller, the order, the order delivery day and the stored line, so unsaved
instances do here. The customer order page's requests run through them end to
end, with the week and the day that close them, in
``tests_viewsets/test_customer_order_page_scoping.py``.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import pytest
import time_machine
from django.utils import timezone

from apps.commissioning.errors import (
    OrderContentAmountNegative,
    OrderContentOfferNotFinalized,
    OrderContentOfferNotInOfferGroup,
    OrderContentOfferRequired,
    OrderContentOfferWeekMismatch,
    OrderContentOfficeOnly,
    OrderDayNotOffered,
)
from apps.commissioning.models import (
    Offer,
    Order,
    OrderContent,
    OrdersDeliveryDay,
    Reseller,
    ShareArticle,
)
from apps.commissioning.services.customer_order_policy import (
    _OFFER_FIELDS,
    _OFFICE_LINE_FIELDS,
    assert_customer_amount_not_negative,
    assert_customer_line_deletable,
    assert_customer_line_write_allowed,
    assert_customer_orderable_offer,
    assert_customer_ordering_open,
    drop_customer_offer_fields,
    drop_customer_order_days,
    ordering_deadline,
)
from apps.commissioning.services.order_content_service import (
    _UPDATABLE_ORDER_CONTENT_FIELDS,
)
from apps.commissioning.viewsets.resellers_viewsets import (
    _ORDER_CONTENT_OFFICE_ONLY_FIELDS,
)

OWN_GROUP = "group-own"
ORDER_WEEK = {"year": 2026, "delivery_week": 15}


def _offer(**fields: Any) -> Offer:
    """A finalized offer of the reseller's group for the order's week."""
    return Offer(
        **{"offer_group_id": OWN_GROUP, "is_finalized": True, **ORDER_WEEK, **fields}
    )


def _new_line(offer: Offer | None, **fields: Any) -> dict[str, Any]:
    return {"offer": offer, **ORDER_WEEK, "amount": Decimal("6.000"), **fields}


@pytest.fixture()
def reseller() -> Reseller:
    return Reseller(offer_group_id=OWN_GROUP)


class TestOrderableOffer:
    def test_a_finalized_offer_of_the_group_and_week_passes(self, reseller):
        assert_customer_orderable_offer(_new_line(_offer()), reseller)

    def test_a_line_without_offer_is_refused(self, reseller):
        with pytest.raises(OrderContentOfferRequired):
            assert_customer_orderable_offer(_new_line(None), reseller)

    def test_a_line_with_an_article_is_refused(self, reseller):
        line = _new_line(_offer(), share_article=ShareArticle(name="Carrots"))

        with pytest.raises(OrderContentOfferRequired):
            assert_customer_orderable_offer(line, reseller)

    def test_an_offer_of_another_group_is_refused(self, reseller):
        line = _new_line(_offer(offer_group_id="group-other"))

        with pytest.raises(OrderContentOfferNotInOfferGroup):
            assert_customer_orderable_offer(line, reseller)

    def test_a_reseller_without_group_orders_no_offer(self):
        with pytest.raises(OrderContentOfferNotInOfferGroup):
            assert_customer_orderable_offer(
                _new_line(_offer()), Reseller(offer_group_id=None)
            )

    def test_a_draft_offer_is_refused(self, reseller):
        with pytest.raises(OrderContentOfferNotFinalized):
            assert_customer_orderable_offer(
                _new_line(_offer(is_finalized=False)), reseller
            )

    @pytest.mark.parametrize(
        "week", [{"delivery_week": 16}, {"year": 2025}], ids=["week", "year"]
    )
    def test_an_offer_of_another_week_is_refused(self, reseller, week):
        with pytest.raises(OrderContentOfferWeekMismatch):
            assert_customer_orderable_offer(_new_line(_offer(**week)), reseller)


class TestAmountNotNegative:
    @pytest.mark.parametrize(
        "amount", [None, Decimal("0.000"), Decimal("-0.000"), Decimal("0.001")]
    )
    def test_no_amount_zero_and_more_pass(self, amount):
        assert_customer_amount_not_negative({"amount": amount})

    def test_a_write_without_amount_passes(self):
        assert_customer_amount_not_negative({"note": "ring twice"})

    @pytest.mark.parametrize("amount", [Decimal("-0.001"), Decimal("-6.000")])
    def test_a_negative_amount_is_refused(self, amount):
        with pytest.raises(OrderContentAmountNegative) as refused:
            assert_customer_amount_not_negative({"amount": amount})

        assert refused.value.field == "amount"


class TestDropOrderDays:
    def test_the_order_days_are_dropped_and_the_rest_kept(self):
        offer = _offer()
        line = _new_line(
            offer,
            harvesting_day=4,
            packing_day=4,
            washing_day=4,
            cleaning_day=None,
            last_possible_ordering_day=6,
        )

        drop_customer_order_days(line)

        assert line == _new_line(offer)

    def test_a_line_without_days_stays_as_it_is(self):
        offer = _offer()
        line = _new_line(offer)

        drop_customer_order_days(line)

        assert line == _new_line(offer)


class TestDropOfferFields:
    def test_the_fields_the_offer_gives_are_dropped_and_the_rest_kept(self):
        offer = _offer()
        line = _new_line(
            offer,
            description="Bunch",
            unit="BUNCH",
            size="L",
            sort="Nantes",
            washing=True,
            cleaning=True,
            comes_from_long_term_storage=True,
            note="Ring twice",
        )

        drop_customer_offer_fields(line)

        assert line == _new_line(offer, note="Ring twice")


# A line the office added without an offer, as it is stored.
OFFICE_LINE = {
    "amount": Decimal("10.000"),
    "description": "Basil, loose",
    "unit": "G",
    "size": "M",
    "sort": "Genovese",
    "note": "For the deli counter",
    "washing": True,
    "cleaning": False,
    "comes_from_long_term_storage": False,
}


def _stored_line(offer: Offer | None, **fields: Any) -> OrderContent:
    """A line of the reseller's order for the order's week."""
    order = Order(reseller=Reseller(offer_group_id=OWN_GROUP), **ORDER_WEEK)
    return OrderContent(order=order, offer=offer, **{**OFFICE_LINE, **fields})


# Offers of the order's week that the customer's page doesn't list.
UNORDERABLE_OFFERS = {
    "draft": {"is_finalized": False},
    "other group": {"offer_group_id": "group-other"},
    "other week": {"delivery_week": 16},
}

# A change of each field a line takes from its offer, from ``OFFICE_LINE``.
OFFER_FIELD_CHANGES = [
    ("description", "Basil, 1 kg bunch"),
    ("description", None),
    ("unit", "KG"),
    ("size", "L"),
    ("sort", "Thai"),
    ("washing", False),
    ("cleaning", True),
    ("comes_from_long_term_storage", True),
]


class TestLineWriteAllowed:
    def test_a_new_line_sets_its_amount(self):
        assert_customer_line_write_allowed({"amount": Decimal("6.000")}, None)

    @pytest.mark.parametrize("amount", [Decimal("0.000"), Decimal("500.000")])
    def test_a_line_of_an_offer_takes_another_amount(self, amount):
        assert_customer_line_write_allowed({"amount": amount}, _stored_line(_offer()))

    def test_a_line_of_an_offer_takes_another_note(self):
        assert_customer_line_write_allowed(
            {"note": "Ring twice"}, _stored_line(_offer())
        )

    @pytest.mark.parametrize("field, value", OFFER_FIELD_CHANGES)
    def test_a_change_to_what_the_offer_gives_a_line_is_refused(self, field, value):
        with pytest.raises(OrderContentOfficeOnly) as refused:
            assert_customer_line_write_allowed({field: value}, _stored_line(_offer()))

        assert refused.value.field == field

    def test_a_line_of_an_offer_takes_its_stored_values_again(self):
        assert_customer_line_write_allowed(dict(OFFICE_LINE), _stored_line(_offer()))

    def test_a_line_without_offer_takes_its_stored_values_again(self):
        assert_customer_line_write_allowed(dict(OFFICE_LINE), _stored_line(None))

    def test_the_stored_amount_is_compared_as_a_number(self):
        assert_customer_line_write_allowed(
            {"amount": Decimal("10")}, _stored_line(None)
        )

    def test_a_write_of_no_line_field_passes_on_a_line_without_offer(self):
        """The order's year and week don't change a stored line, and the server
        replaces a sent price with the stored one (``tier_price``)."""
        line = {**ORDER_WEEK, "price_per_unit": Decimal("0.01")}

        assert_customer_line_write_allowed(line, _stored_line(None))

    @pytest.mark.parametrize(
        "field, value",
        [
            ("amount", Decimal("500.000")),
            ("amount", Decimal("10.001")),
            ("amount", Decimal("0.000")),
            ("amount", None),
            ("note", "Free delivery"),
            *OFFER_FIELD_CHANGES,
        ],
    )
    def test_a_change_to_a_line_without_offer_is_refused(self, field, value):
        """An empty amount zeroes the line, as the update stores it."""
        with pytest.raises(OrderContentOfficeOnly) as refused:
            assert_customer_line_write_allowed({field: value}, _stored_line(None))

        assert refused.value.field == field

    @pytest.mark.parametrize(
        "offer", UNORDERABLE_OFFERS.values(), ids=UNORDERABLE_OFFERS
    )
    @pytest.mark.parametrize(
        "field, value", [("amount", Decimal("500.000")), ("note", "Free delivery")]
    )
    def test_a_line_on_an_offer_the_page_doesnt_list_is_the_offices(
        self, offer, field, value
    ):
        stored = _stored_line(_offer(**offer))

        with pytest.raises(OrderContentOfficeOnly):
            assert_customer_line_write_allowed({field: value}, stored)

    @pytest.mark.parametrize(
        "field, sent, stored",
        [
            ("amount", Decimal("0.000"), None),
            ("amount", None, Decimal("0.000")),
            ("note", "", None),
            ("note", None, ""),
            ("cleaning", None, False),
            ("cleaning", False, None),
        ],
    )
    def test_an_empty_value_takes_the_place_of_another(self, field, sent, stored):
        assert_customer_line_write_allowed(
            {field: sent}, _stored_line(None, **{field: stored})
        )

    @pytest.mark.parametrize("has_offer", [True, False], ids=["offer", "no offer"])
    def test_a_negative_amount_is_refused_as_negative(self, has_offer):
        stored = _stored_line(_offer() if has_offer else None)

        with pytest.raises(OrderContentAmountNegative):
            assert_customer_line_write_allowed({"amount": Decimal("-1.000")}, stored)


class TestLineDeletable:
    def test_a_line_of_an_offer_the_page_lists_may_go(self):
        assert_customer_line_deletable(_stored_line(_offer()))

    @pytest.mark.parametrize(
        "offer",
        [None, *UNORDERABLE_OFFERS.values()],
        ids=["no offer", *UNORDERABLE_OFFERS],
    )
    def test_an_office_line_stays(self, offer):
        stored = _stored_line(None if offer is None else _offer(**offer))

        with pytest.raises(OrderContentOfficeOnly):
            assert_customer_line_deletable(stored)


class TestReadOnlyFields:
    def test_every_field_the_update_writes_has_a_customer_rule(self):
        """Every field the update writes is read-only on an office line, or one
        with a rule of its own: the line's offer or article, price, rabatt and
        tax rate. A field the update learns to write fails here until it is one
        or the other."""
        own_rules = {"offer", "share_article", "price_per_unit"}

        assert _UPDATABLE_ORDER_CONTENT_FIELDS <= (
            set(_OFFICE_LINE_FIELDS) | own_rules | _ORDER_CONTENT_OFFICE_ONLY_FIELDS
        )

    def test_a_customer_line_changes_only_its_amount_and_note(self):
        assert set(_OFFICE_LINE_FIELDS) - set(_OFFER_FIELDS) == {"amount", "note"}


class TestOrderingDeadline:
    """Week 15 of 2026 starts on Monday, 6 April."""

    def test_it_is_the_last_day_of_the_order_week_at_its_minute(self):
        order_day = OrdersDeliveryDay(
            default_last_possible_ordering_day=1,
            default_last_possible_ordering_time=datetime.time(10, 30, 45),
        )

        deadline = ordering_deadline(order_day, 2026, 15)

        assert deadline == timezone.make_aware(datetime.datetime(2026, 4, 7, 10, 30))

    def test_without_a_time_it_is_the_end_of_the_day(self):
        order_day = OrdersDeliveryDay(default_last_possible_ordering_day=0)

        deadline = ordering_deadline(order_day, 2026, 15)

        assert timezone.localtime(deadline) == timezone.make_aware(
            datetime.datetime.combine(datetime.date(2026, 4, 6), datetime.time.max)
        )

    def test_a_day_without_last_day_sets_none(self):
        order_day = OrdersDeliveryDay(
            default_last_possible_ordering_time=datetime.time(10, 30)
        )

        assert ordering_deadline(order_day, 2026, 15) is None


class TestOrderWithoutDay:
    """An order without a delivery day has no order delivery day to take a
    deadline from; only its week closes it."""

    @pytest.fixture(autouse=True)
    def _week_13(self):
        with time_machine.travel(datetime.datetime(2026, 3, 23, 12, 0), tick=False):
            yield

    def test_its_lines_stay_open_in_an_open_week(self):
        assert_customer_ordering_open(2026, 15, None, new_line=False)

    def test_it_takes_no_new_line(self):
        with pytest.raises(OrderDayNotOffered):
            assert_customer_ordering_open(2026, 15, None, new_line=True)
