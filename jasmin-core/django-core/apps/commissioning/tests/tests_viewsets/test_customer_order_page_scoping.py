"""Permission + scoping smoke tests for the Customer Order page.

A user whose only role is ``customer`` should be able to use every
endpoint hit by ``src/features/customer/pages/CustomerOrderPage.tsx`` for *their
own* reseller (read+edit own reseller, list/create/update/delete own
order contents, read own delivery notes / invoices) and must be denied (403)
or get nothing for everything else. Their own crate lines they may read but not
write, since a crate line write carries the line's price and rabatt. Offers,
delivery notes and invoices reach them once finalized; drafts stay hidden.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
import time_machine
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.commissioning.models import (
    CrateOrderContent,
    DeliveryNoteReseller,
    InvoiceReseller,
    InvoiceResellerContent,
    OrderContent,
    OrdersDeliveryDay,
)
from apps.commissioning.services import DeliveryNoteService
from apps.commissioning.tests.factories.accounts import JasminUserFactory
from apps.commissioning.tests.factories.basics import CrateFactory, ShareArticleFactory
from apps.commissioning.tests.factories.days import OrdersDeliveryDayFactory
from apps.commissioning.tests.factories.members import MemberFactory
from apps.commissioning.tests.factories.resellers import (
    DeliveryNoteContentFactory,
    DeliveryNoteResellerFactory,
    InvoiceResellerFactory,
    OfferFactory,
    OfferGroupFactory,
    OrderContentFactory,
    OrderFactory,
    ResellerFactory,
)
from apps.shared.tenants.models import TenantSettings

# --- Fixtures -------------------------------------------------------------


@pytest.fixture(autouse=True)
def _frozen_clock():
    """The orders here are for week 15 of 2026, which a customer's page and the
    server close once it is past: the clock stands on Monday of week 13."""
    with time_machine.travel(datetime.datetime(2026, 3, 23, 12, 0), tick=False):
        yield


@pytest.fixture(autouse=True)
def order_day(tenant):
    """The farm delivers orders on day 2, the orders' day here, with no
    ordering deadline: a customer's new line needs an order delivery day."""
    return OrdersDeliveryDayFactory(day_number=2)


@pytest.fixture()
def customer_caller(tenant):
    """A user whose only role is ``customer``, linked to one reseller.

    The reseller belongs to its own offer group so we can also assert that
    cross-group offers are hidden by `scope_to_offer_group`.
    """
    user = JasminUserFactory(roles=["customer"])
    offer_group = OfferGroupFactory()
    reseller = ResellerFactory(linked_user=user, offer_group=offer_group)
    return user, reseller, offer_group


@pytest.fixture()
def customer_caller_client(customer_caller):
    user, _r, _g = customer_caller
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture()
def other_reseller(tenant):
    """An unrelated reseller in its own offer group — for negative checks."""
    return ResellerFactory(offer_group=OfferGroupFactory())


# --- ResellerViewSet ------------------------------------------------------


class TestCustomerOrderPage_ResellerScoping:
    def test_list_returns_only_own_reseller(
        self, customer_caller_client, customer_caller, other_reseller
    ):
        _u, my_reseller, _g = customer_caller
        resp = customer_caller_client.get("/api/commissioning/resellers/")
        assert resp.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in resp.data}
        assert ids == {my_reseller.id}

    def test_retrieve_self_ok(self, customer_caller_client, customer_caller):
        _u, my_reseller, _g = customer_caller
        resp = customer_caller_client.get(
            f"/api/commissioning/resellers/{my_reseller.id}/"
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["id"] == my_reseller.id

    def test_retrieve_other_404(self, customer_caller_client, other_reseller):
        resp = customer_caller_client.get(
            f"/api/commissioning/resellers/{other_reseller.id}/"
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_partial_update_self_ok(self, customer_caller_client, customer_caller):
        _u, my_reseller, _g = customer_caller
        resp = customer_caller_client.patch(
            f"/api/commissioning/resellers/{my_reseller.id}/",
            {"name_for_member_pages": "My Shop"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK

    def test_partial_update_other_404(self, customer_caller_client, other_reseller):
        resp = customer_caller_client.patch(
            f"/api/commissioning/resellers/{other_reseller.id}/",
            {"name_for_member_pages": "x"},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_partial_update_self_privileged_field_forbidden(
        self, customer_caller_client, customer_caller
    ):
        """A customer may edit display fields on their own reseller row, but
        NOT privileged ones — self-assigning a cheaper offer_group (which drives
        which offers/prices they see and order at) or flipping activation /
        billing fields is a pricing / privilege hole."""
        _u, my_reseller, _g = customer_caller
        other_group = OfferGroupFactory()
        resp = customer_caller_client.patch(
            f"/api/commissioning/resellers/{my_reseller.id}/",
            {"offer_group": other_group.id},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        my_reseller.refresh_from_db()
        assert my_reseller.offer_group_id != other_group.id

    def test_partial_update_self_activation_flag_forbidden(
        self, customer_caller_client, customer_caller
    ):
        _u, my_reseller, _g = customer_caller
        resp = customer_caller_client.patch(
            f"/api/commissioning/resellers/{my_reseller.id}/",
            {"is_active_reseller": True, "customer_number": 99999},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_create_reseller_forbidden(self, customer_caller_client):
        resp = customer_caller_client.post(
            "/api/commissioning/resellers/",
            {"is_reseller": True},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_destroy_self_forbidden(self, customer_caller_client, customer_caller):
        _u, my_reseller, _g = customer_caller
        resp = customer_caller_client.delete(
            f"/api/commissioning/resellers/{my_reseller.id}/"
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# --- OfferViewSet (offer_group-scoped) ------------------------------------


class TestCustomerOrderPage_OfferScoping:
    def test_list_excludes_offers_in_other_groups(
        self, customer_caller_client, customer_caller, other_reseller
    ):
        _u, my_reseller, my_group = customer_caller
        my_offer = OfferFactory(
            offer_group=my_group, year=2026, delivery_week=15, is_finalized=True
        )
        foreign_offer = OfferFactory(
            offer_group=other_reseller.offer_group,
            year=2026,
            delivery_week=15,
            is_finalized=True,
        )

        resp = customer_caller_client.get(
            "/api/commissioning/offers/?year=2026&delivery_week=15"
        )
        assert resp.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in resp.data}
        assert my_offer.id in ids
        assert foreign_offer.id not in ids

    def test_list_hides_draft_offers(self, customer_caller_client, customer_caller):
        _u, _r, my_group = customer_caller
        published = OfferFactory(
            offer_group=my_group, year=2026, delivery_week=15, is_finalized=True
        )
        OfferFactory(offer_group=my_group, year=2026, delivery_week=15)

        resp = customer_caller_client.get(
            "/api/commissioning/offers/?year=2026&delivery_week=15"
        )

        assert resp.status_code == status.HTTP_200_OK
        assert {row["id"] for row in resp.data} == {published.id}

    @pytest.mark.parametrize("role", ["office", "staff"])
    def test_the_office_and_crew_see_draft_offers(self, customer_caller, role):
        _u, _r, my_group = customer_caller
        draft = OfferFactory(offer_group=my_group, year=2026, delivery_week=15)
        client = APIClient()
        client.force_authenticate(user=JasminUserFactory(roles=[role]))

        resp = client.get(
            "/api/commissioning/offers/",
            {"year": 2026, "delivery_week": 15, "offer_group": my_group.id},
        )

        assert resp.status_code == status.HTTP_200_OK
        assert draft.id in {row["id"] for row in resp.data}


# --- OrderContentViewSet --------------------------------------------------


class TestCustomerOrderPage_OrderContentScoping:
    def test_list_returns_only_own(
        self, customer_caller_client, customer_caller, other_reseller
    ):
        _u, my_reseller, _g = customer_caller
        my_oc = OrderContentFactory(
            order=OrderFactory(reseller=my_reseller, year=2026, delivery_week=15)
        )
        OrderContentFactory(
            order=OrderFactory(reseller=other_reseller, year=2026, delivery_week=15)
        )
        # The list endpoint shape is custom (returns dict), so just call
        # the underlying queryset path via the regular DRF retrieve to
        # confirm scoping. Use the get_object route instead.
        resp = customer_caller_client.get(
            f"/api/commissioning/order_contents/{my_oc.id}/"
        )
        assert resp.status_code == status.HTTP_200_OK

    def test_retrieve_other_resellers_oc_404(
        self, customer_caller_client, other_reseller
    ):
        foreign = OrderContentFactory(order=OrderFactory(reseller=other_reseller))
        resp = customer_caller_client.get(
            f"/api/commissioning/order_contents/{foreign.id}/"
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_create_for_other_reseller_rejected(
        self, customer_caller_client, other_reseller
    ):
        # Customer tries to write order content with a `reseller` field
        # pointing at someone else.
        resp = customer_caller_client.post(
            "/api/commissioning/order_contents/",
            {"reseller": other_reseller.id, "amount": "1.000"},
            format="json",
        )
        assert resp.status_code in (
            status.HTTP_400_BAD_REQUEST,  # serializer rejects bad payload first
            status.HTTP_403_FORBIDDEN,
        )

    def test_update_other_resellers_oc_404(
        self, customer_caller_client, other_reseller
    ):
        foreign = OrderContentFactory(order=OrderFactory(reseller=other_reseller))
        resp = customer_caller_client.patch(
            f"/api/commissioning/order_contents/{foreign.id}/",
            {"amount": "5.000"},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_destroy_other_resellers_oc_404(
        self, customer_caller_client, other_reseller
    ):
        foreign = OrderContentFactory(order=OrderFactory(reseller=other_reseller))
        resp = customer_caller_client.delete(
            f"/api/commissioning/order_contents/{foreign.id}/"
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_customer_cannot_set_price_on_own_oc(
        self, customer_caller_client, customer_caller
    ):
        # Even on their OWN order content, a customer must not set
        # price_per_unit / rabatt / tax_rate — that would self-underbill into
        # the delivery note + invoice. Price is resolved server-side.
        _u, my_reseller, _g = customer_caller
        own = OrderContentFactory(
            order=OrderFactory(reseller=my_reseller, year=2026, delivery_week=15),
            price_per_unit="4.00",
        )
        resp = customer_caller_client.patch(
            f"/api/commissioning/order_contents/{own.id}/",
            {"price_per_unit": "0.01", "rabatt": "100"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        own.refresh_from_db()
        assert own.price_per_unit == Decimal("4.00")


# --- OrderContentViewSet: what a customer may order ------------------------

ORDER_CONTENTS_URL = "/api/commissioning/order_contents/"


def _customer_create_body(reseller, **line):
    """The customer order page's create body (``useCustomerOrderMutations``).
    It carries no ``price_per_unit``: the server prices a customer's line
    itself (``TestCustomerOrderPagePricing``)."""
    return {
        "year": 2026,
        "delivery_week": 15,
        "day_number": 2,
        "reseller": reseller.id,
        "amount": "3.000",
        "unit": "KG",
        **line,
    }


class TestCustomerOrderPage_OrderContentOfferScoping:
    def test_create_offer_of_own_offer_group_ok(
        self, customer_caller_client, customer_caller
    ):
        _u, my_reseller, my_group = customer_caller
        offer = OfferFactory(
            offer_group=my_group, is_finalized=True, amount=Decimal("100.000")
        )

        resp = customer_caller_client.post(
            ORDER_CONTENTS_URL,
            _customer_create_body(my_reseller, offer=offer.id),
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        line = OrderContent.objects.get(offer=offer)
        assert line.order.reseller_id == my_reseller.id
        assert line.amount == Decimal("3.000")
        offer.refresh_from_db()
        assert offer.amount == Decimal("97.000")

    def test_create_offer_of_other_offer_group_forbidden(
        self, customer_caller_client, customer_caller, other_reseller
    ):
        _u, my_reseller, _g = customer_caller
        foreign_offer = OfferFactory(
            offer_group=other_reseller.offer_group,
            is_finalized=True,
            amount=Decimal("100.000"),
        )

        resp = customer_caller_client.post(
            ORDER_CONTENTS_URL,
            _customer_create_body(my_reseller, offer=foreign_offer.id),
            format="json",
        )

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["code"] == "order_content.offer_not_in_offer_group"
        assert not OrderContent.objects.filter(offer=foreign_offer).exists()
        foreign_offer.refresh_from_db()
        assert foreign_offer.amount == Decimal("100.000")

    def test_create_when_own_reseller_has_no_offer_group_forbidden(
        self, customer_caller_client, customer_caller
    ):
        # The absent side of the nullable Reseller.offer_group FK: a reseller
        # without an offer group is listed no offers, so it may order none.
        _u, my_reseller, my_group = customer_caller
        offer = OfferFactory(offer_group=my_group, is_finalized=True)
        my_reseller.offer_group = None
        my_reseller.save(update_fields=["offer_group"])

        resp = customer_caller_client.post(
            ORDER_CONTENTS_URL,
            _customer_create_body(my_reseller, offer=offer.id),
            format="json",
        )

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["code"] == "order_content.offer_not_in_offer_group"
        assert not OrderContent.objects.filter(offer=offer).exists()

    def test_create_share_article_line_forbidden(
        self, customer_caller_client, customer_caller
    ):
        _u, my_reseller, _g = customer_caller
        article = ShareArticleFactory()

        resp = customer_caller_client.post(
            ORDER_CONTENTS_URL,
            _customer_create_body(my_reseller, share_article=article.id),
            format="json",
        )

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["code"] == "order_content.offer_required"
        assert not OrderContent.objects.filter(share_article=article).exists()

    def test_create_offer_not_finalized_forbidden(
        self, customer_caller_client, customer_caller
    ):
        """The page lists only finalized offers: a draft's prices may still be
        missing or change, and the server prices the line from them."""
        _u, my_reseller, my_group = customer_caller
        draft = OfferFactory(
            offer_group=my_group, is_finalized=False, amount=Decimal("100.000")
        )

        resp = customer_caller_client.post(
            ORDER_CONTENTS_URL,
            _customer_create_body(my_reseller, offer=draft.id),
            format="json",
        )

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["code"] == "order_content.offer_not_finalized"
        assert not OrderContent.objects.filter(offer=draft).exists()
        draft.refresh_from_db()
        assert draft.amount == Decimal("100.000")

    @pytest.mark.parametrize(
        "year, delivery_week", [(2026, 14), (2025, 15)], ids=["week", "year"]
    )
    def test_create_offer_of_another_week_forbidden(
        self, customer_caller_client, customer_caller, year, delivery_week
    ):
        """An order of week 15 of 2026 takes only that week's offers; another
        week's would price the line and give it its stock."""
        _u, my_reseller, my_group = customer_caller
        other_week = OfferFactory(
            offer_group=my_group,
            is_finalized=True,
            year=year,
            delivery_week=delivery_week,
            amount=Decimal("100.000"),
        )

        resp = customer_caller_client.post(
            ORDER_CONTENTS_URL,
            _customer_create_body(my_reseller, offer=other_week.id),
            format="json",
        )

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["code"] == "order_content.offer_week_mismatch"
        assert not OrderContent.objects.filter(offer=other_week).exists()
        other_week.refresh_from_db()
        assert other_week.amount == Decimal("100.000")

    def test_the_office_orders_a_draft_offer(self, api_client, customer_caller):
        """The office's order page offers every offer of the week, drafts
        included."""
        _u, my_reseller, my_group = customer_caller
        draft = OfferFactory(offer_group=my_group, is_finalized=False)

        resp = api_client.post(
            ORDER_CONTENTS_URL,
            _customer_create_body(my_reseller, offer=draft.id),
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert OrderContent.objects.filter(offer=draft).exists()

    def test_patch_changing_offer_forbidden(
        self, customer_caller_client, customer_caller
    ):
        _u, my_reseller, my_group = customer_caller
        booked = OfferFactory(offer_group=my_group, amount=Decimal("90.000"))
        other = OfferFactory(offer_group=my_group, amount=Decimal("100.000"))
        line = OrderContentFactory(
            order=OrderFactory(reseller=my_reseller),
            offer=booked,
            share_article=None,
            amount=Decimal("10.000"),
        )

        resp = customer_caller_client.patch(
            f"{ORDER_CONTENTS_URL}{line.id}/",
            {"offer": other.id, "amount": "10.000"},
            format="json",
        )

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["code"] == "order_content.item_change_forbidden"
        line.refresh_from_db()
        assert line.offer_id == booked.id
        booked.refresh_from_db()
        other.refresh_from_db()
        assert booked.amount == Decimal("90.000")
        assert other.amount == Decimal("100.000")

    def test_patch_adding_share_article_forbidden(
        self, customer_caller_client, customer_caller
    ):
        _u, my_reseller, my_group = customer_caller
        booked = OfferFactory(offer_group=my_group, amount=Decimal("90.000"))
        line = OrderContentFactory(
            order=OrderFactory(reseller=my_reseller),
            offer=booked,
            share_article=None,
            amount=Decimal("10.000"),
        )

        resp = customer_caller_client.patch(
            f"{ORDER_CONTENTS_URL}{line.id}/",
            {"share_article": ShareArticleFactory().id},
            format="json",
        )

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["code"] == "order_content.item_change_forbidden"
        line.refresh_from_db()
        assert line.share_article_id is None
        assert line.amount == Decimal("10.000")

    def test_patch_resending_current_offer_ok(
        self, customer_caller_client, customer_caller
    ):
        _u, my_reseller, my_group = customer_caller
        booked = OfferFactory(
            offer_group=my_group, amount=Decimal("90.000"), is_finalized=True
        )
        line = OrderContentFactory(
            order=OrderFactory(reseller=my_reseller),
            offer=booked,
            share_article=None,
            amount=Decimal("10.000"),
        )

        resp = customer_caller_client.patch(
            f"{ORDER_CONTENTS_URL}{line.id}/",
            {"offer": booked.id, "amount": "12.000"},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        line.refresh_from_db()
        assert line.amount == Decimal("12.000")
        booked.refresh_from_db()
        assert booked.amount == Decimal("88.000")

    def test_patch_finalization_stamps_not_applied(
        self, customer_caller_client, customer_caller
    ):
        user, my_reseller, my_group = customer_caller
        booked = OfferFactory(
            offer_group=my_group, amount=Decimal("90.000"), is_finalized=True
        )
        line = OrderContentFactory(
            order=OrderFactory(reseller=my_reseller),
            offer=booked,
            share_article=None,
            amount=Decimal("10.000"),
        )

        resp = customer_caller_client.patch(
            f"{ORDER_CONTENTS_URL}{line.id}/",
            {
                "amount": "12.000",
                "finalized_by": user.pk,
                "finalized_at": "2026-04-06T12:00:00Z",
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        line.refresh_from_db()
        assert line.finalized_by_id is None
        assert line.finalized_at is None
        assert line.is_finalized is False
        assert line.amount == Decimal("12.000")


# --- OrderContentViewSet: how a customer's order line is priced -------------


@pytest.fixture()
def tiered_offer(tenant, customer_caller):
    """An offer of the customer's own group in PUs of 2 kg, at 2.00 / 1.80 /
    1.60 per kg from 1 / 5 / 10 PU under the tenant's tiers."""
    _u, _r, my_group = customer_caller
    settings, _ = TenantSettings.objects.get_or_create(
        tenant=tenant,
        valid_until=None,
        defaults={"valid_from": timezone.now() - datetime.timedelta(days=365)},
    )
    settings.used_tiers_for_offers = [1, 5, 10]
    settings.save()
    return OfferFactory(
        offer_group=my_group,
        is_finalized=True,
        amount=Decimal("100.000"),
        amount_per_pu=Decimal("2.000"),
        price_1=Decimal("2.00"),
        price_2=Decimal("1.80"),
        price_3=Decimal("1.60"),
    )


def _page_body(reseller, offer, pu, **extra):
    """What the customer order page saves for ``pu`` PU of ``offer``: the
    amount in the offer's unit, ``pu × amount_per_pu`` to three decimals."""
    amount = f"{pu * offer.amount_per_pu:.3f}"
    return _customer_create_body(reseller, offer=offer.id, amount=amount, **extra)


def _line_of(offer):
    return OrderContent.objects.get(offer=offer)


class TestCustomerOrderPagePricing:
    def test_create_replaces_a_sent_price_with_the_tier_price(
        self, customer_caller_client, customer_caller, tiered_offer
    ):
        """A client that still prices the line itself sends its own price,
        which a customer could set to anything."""
        _u, my_reseller, _g = customer_caller
        body = _page_body(my_reseller, tiered_offer, 6, price_per_unit="0.01")

        resp = customer_caller_client.post(ORDER_CONTENTS_URL, body, format="json")

        assert resp.status_code == status.HTTP_200_OK, resp.data
        line = _line_of(tiered_offer)
        assert line.amount == Decimal("12.000")
        assert line.price_per_unit == Decimal("1.80")
        assert resp.data["price_per_unit"] == Decimal("1.80")

    def test_create_without_a_price_stores_the_tier_price(
        self, customer_caller_client, customer_caller, tiered_offer
    ):
        _u, my_reseller, _g = customer_caller
        body = _page_body(my_reseller, tiered_offer, 2)

        resp = customer_caller_client.post(ORDER_CONTENTS_URL, body, format="json")

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert _line_of(tiered_offer).price_per_unit == Decimal("2.00")

    @pytest.mark.parametrize(
        "pu, expected", [(4, "2.00"), (5, "1.80"), (9, "1.80"), (10, "1.60")]
    )
    def test_the_tier_follows_the_pu_count_not_the_amount(
        self, customer_caller_client, customer_caller, tiered_offer, pu, expected
    ):
        """4 PU are 8 kg: priced as 4 PU, below the second tier, though 8 is
        past it."""
        _u, my_reseller, _g = customer_caller
        body = _page_body(my_reseller, tiered_offer, pu)

        resp = customer_caller_client.post(ORDER_CONTENTS_URL, body, format="json")

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert _line_of(tiered_offer).price_per_unit == Decimal(expected)

    def test_an_amount_change_picks_the_tier_again(
        self, customer_caller_client, customer_caller, tiered_offer
    ):
        _u, my_reseller, _g = customer_caller
        body = _page_body(my_reseller, tiered_offer, 2)
        customer_caller_client.post(ORDER_CONTENTS_URL, body, format="json")
        url = f"{ORDER_CONTENTS_URL}{_line_of(tiered_offer).id}/"

        up = customer_caller_client.patch(
            url, {"amount": "20.000", "price_per_unit": "0.01"}, format="json"
        )
        assert up.status_code == status.HTTP_200_OK, up.data
        assert _line_of(tiered_offer).price_per_unit == Decimal("1.60")

        down = customer_caller_client.patch(url, {"amount": "8.000"}, format="json")
        assert down.status_code == status.HTTP_200_OK, down.data
        line = _line_of(tiered_offer)
        assert line.amount == Decimal("8.000")
        assert line.price_per_unit == Decimal("2.00")

    @pytest.mark.parametrize("amount", ["10.000", "12.000"], ids=["same", "new"])
    def test_a_price_the_office_set_stays(
        self, customer_caller_client, customer_caller, tiered_offer, amount
    ):
        """10 kg are 5 PU, at 1.80 under the tiers; the office priced them at
        1.50."""
        _u, my_reseller, _g = customer_caller
        line = OrderContentFactory(
            order=OrderFactory(reseller=my_reseller),
            offer=tiered_offer,
            share_article=None,
            amount=Decimal("10.000"),
            price_per_unit=Decimal("1.50"),
        )

        resp = customer_caller_client.patch(
            f"{ORDER_CONTENTS_URL}{line.id}/", {"amount": amount}, format="json"
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        line.refresh_from_db()
        assert line.amount == Decimal(amount)
        assert line.price_per_unit == Decimal("1.50")

    def test_a_write_without_amount_keeps_the_price(
        self, customer_caller_client, customer_caller, tiered_offer
    ):
        _u, my_reseller, _g = customer_caller
        body = _page_body(my_reseller, tiered_offer, 6)
        customer_caller_client.post(ORDER_CONTENTS_URL, body, format="json")
        line = _line_of(tiered_offer)

        resp = customer_caller_client.patch(
            f"{ORDER_CONTENTS_URL}{line.id}/",
            {"price_per_unit": "0.01"},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        line.refresh_from_db()
        assert line.amount == Decimal("12.000")
        assert line.price_per_unit == Decimal("1.80")

    @pytest.mark.parametrize(
        "field, value", [("rabatt", 100), ("tax_rate", "0.00"), ("is_finalized", True)]
    )
    def test_a_create_setting_an_office_only_field_is_forbidden(
        self, customer_caller_client, customer_caller, tiered_offer, field, value
    ):
        _u, my_reseller, _g = customer_caller
        body = _page_body(my_reseller, tiered_offer, 6, **{field: value})

        resp = customer_caller_client.post(ORDER_CONTENTS_URL, body, format="json")

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert not OrderContent.objects.filter(offer=tiered_offer).exists()
        tiered_offer.refresh_from_db()
        assert tiered_offer.amount == Decimal("100.000")

    @pytest.mark.parametrize(
        "field, value", [("rabatt", 100), ("tax_rate", "0.00"), ("is_finalized", True)]
    )
    def test_a_patch_setting_an_office_only_field_is_forbidden(
        self, customer_caller_client, customer_caller, tiered_offer, field, value
    ):
        _u, my_reseller, _g = customer_caller
        body = _page_body(my_reseller, tiered_offer, 6)
        customer_caller_client.post(ORDER_CONTENTS_URL, body, format="json")
        line = _line_of(tiered_offer)

        resp = customer_caller_client.patch(
            f"{ORDER_CONTENTS_URL}{line.id}/",
            {"amount": "20.000", field: value},
            format="json",
        )

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        line.refresh_from_db()
        assert (line.amount, line.price_per_unit) == (
            Decimal("12.000"),
            Decimal("1.80"),
        )
        assert (line.rabatt, line.is_finalized) == (None, False)

    def test_the_delivery_note_line_carries_the_tier_price(
        self, customer_caller_client, customer_caller, tiered_offer
    ):
        _u, my_reseller, _g = customer_caller
        body = _page_body(my_reseller, tiered_offer, 6)
        customer_caller_client.post(ORDER_CONTENTS_URL, body, format="json")

        delivery_note = DeliveryNoteService.create_from_order(
            _line_of(tiered_offer).order
        )

        note_line = delivery_note.items.get()
        assert note_line.price_per_unit == Decimal("1.80")
        assert note_line.line_netto == Decimal("21.60")

    def test_the_office_keeps_the_price_it_sends(
        self, api_client, customer_caller, tiered_offer
    ):
        """The same page on the office's route prices the line itself, and the
        office may price a line off its tier."""
        _u, my_reseller, _g = customer_caller
        body = _page_body(my_reseller, tiered_offer, 6, price_per_unit="1.23")

        created = api_client.post(ORDER_CONTENTS_URL, body, format="json")
        assert created.status_code == status.HTTP_200_OK, created.data
        line = _line_of(tiered_offer)
        assert line.price_per_unit == Decimal("1.23")

        patched = api_client.patch(
            f"{ORDER_CONTENTS_URL}{line.id}/",
            {"amount": "20.000", "price_per_unit": "1.11"},
            format="json",
        )
        assert patched.status_code == status.HTTP_200_OK, patched.data
        line.refresh_from_db()
        assert line.price_per_unit == Decimal("1.11")


@pytest.fixture()
def office_article_line(customer_caller):
    """An article the office added to the customer's order without an offer, at
    its own price and rabatt."""
    _u, my_reseller, _g = customer_caller
    return OrderContentFactory(
        order=OrderFactory(reseller=my_reseller),
        unit="G",
        description="Basil, loose",
        sort="Genovese",
        note="For the deli counter",
        price_per_unit=Decimal("2.50"),
        rabatt=20,
    )


class TestCustomerOrderPageAmounts:
    """A customer orders no negative amount: the line would take its price,
    reach the delivery note and the invoice as a credit, and hand its PU back
    to the offer's stock. Nor do they change the amount of a line the office
    added without an offer."""

    def test_a_negative_amount_is_refused_on_create(
        self, customer_caller_client, customer_caller, tiered_offer
    ):
        _u, my_reseller, _g = customer_caller
        body = _page_body(my_reseller, tiered_offer, -3)

        resp = customer_caller_client.post(ORDER_CONTENTS_URL, body, format="json")

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["code"] == "order_content.amount_negative"
        assert not OrderContent.objects.filter(offer=tiered_offer).exists()
        tiered_offer.refresh_from_db()
        assert tiered_offer.amount == Decimal("100.000")

    def test_a_negative_amount_is_refused_on_patch(
        self, customer_caller_client, customer_caller, tiered_offer
    ):
        _u, my_reseller, _g = customer_caller
        body = _page_body(my_reseller, tiered_offer, 6)
        customer_caller_client.post(ORDER_CONTENTS_URL, body, format="json")
        line = _line_of(tiered_offer)

        resp = customer_caller_client.patch(
            f"{ORDER_CONTENTS_URL}{line.id}/", {"amount": "-12.000"}, format="json"
        )

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["code"] == "order_content.amount_negative"
        line.refresh_from_db()
        assert (line.amount, line.price_per_unit) == (
            Decimal("12.000"),
            Decimal("1.80"),
        )
        tiered_offer.refresh_from_db()
        assert tiered_offer.amount == Decimal("94.000")

    def test_a_negative_amount_is_refused_on_a_line_without_offer(
        self, customer_caller_client, customer_caller
    ):
        """An article the office added to the order keeps its own price, which
        a negative amount would turn into a credit too."""
        _u, my_reseller, _g = customer_caller
        line = OrderContentFactory(
            order=OrderFactory(reseller=my_reseller), price_per_unit=Decimal("2.50")
        )

        resp = customer_caller_client.patch(
            f"{ORDER_CONTENTS_URL}{line.id}/", {"amount": "-10.000"}, format="json"
        )

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["code"] == "order_content.amount_negative"
        line.refresh_from_db()
        assert line.amount == Decimal("10.000")

    @pytest.mark.parametrize("amount", ["500.000", "0.000"])
    def test_an_amount_change_is_refused_on_a_line_without_offer(
        self, customer_caller_client, office_article_line, amount
    ):
        """The page shows the line read-only: another amount would stretch the
        office's price and rabatt over it, with no stock to check it against."""
        line = office_article_line

        resp = customer_caller_client.patch(
            f"{ORDER_CONTENTS_URL}{line.id}/", {"amount": amount}, format="json"
        )

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["code"] == "order_content.office_only"
        line.refresh_from_db()
        assert (line.amount, line.price_per_unit, line.rabatt) == (
            Decimal("10.000"),
            Decimal("2.50"),
            20,
        )

    @pytest.mark.parametrize("amount", ["10.000", "10"])
    def test_the_stored_amount_of_a_line_without_offer_is_accepted(
        self, customer_caller_client, office_article_line, amount
    ):
        """A client that echoes the line's values sends its amount unchanged."""
        line = office_article_line

        resp = customer_caller_client.patch(
            f"{ORDER_CONTENTS_URL}{line.id}/", {"amount": amount}, format="json"
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        line.refresh_from_db()
        assert (line.amount, line.price_per_unit) == (
            Decimal("10.000"),
            Decimal("2.50"),
        )

    def test_the_office_changes_the_amount_of_a_line_without_offer(
        self, api_client, office_article_line
    ):
        line = office_article_line

        resp = api_client.patch(
            f"{ORDER_CONTENTS_URL}{line.id}/", {"amount": "500.000"}, format="json"
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        line.refresh_from_db()
        assert line.amount == Decimal("500.000")

    def test_an_emptied_row_saves_zero(
        self, customer_caller_client, customer_caller, tiered_offer
    ):
        """The page saves 0 for a row whose amount was cleared."""
        _u, my_reseller, _g = customer_caller
        body = _page_body(my_reseller, tiered_offer, 6)
        customer_caller_client.post(ORDER_CONTENTS_URL, body, format="json")
        line = _line_of(tiered_offer)

        resp = customer_caller_client.patch(
            f"{ORDER_CONTENTS_URL}{line.id}/", {"amount": "0.000"}, format="json"
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        line.refresh_from_db()
        assert line.amount == Decimal("0.000")
        tiered_offer.refresh_from_db()
        assert tiered_offer.amount == Decimal("100.000")


# What a customer could send to change ``office_article_line`` besides its
# amount (``TestCustomerOrderPageAmounts``).
OFFICE_LINE_CHANGES = {
    "unit": "KG",
    "size": "L",
    "description": "Basil, 1 kg bunch",
    "sort": "Thai",
    "note": "Free delivery",
    "washing": True,
    "cleaning": True,
    "comes_from_long_term_storage": True,
}


def _office_line_values(line):
    line.refresh_from_db()
    fields = ["amount", "price_per_unit", "rabatt", *OFFICE_LINE_CHANGES]
    return {field: getattr(line, field) for field in fields}


class TestCustomerOrderPageOfficeLines:
    """The delivery note and the invoice take a line the office added without
    an offer from the line itself, its unit, size, sort and description at the
    office's price and rabatt, and the goods flow plans its work from it. The
    page shows it read-only, as it does a line the office added on an offer the
    page doesn't list, and a customer changes or deletes nothing on either."""

    @pytest.mark.parametrize("field, value", list(OFFICE_LINE_CHANGES.items()))
    def test_a_change_is_refused(
        self, customer_caller_client, office_article_line, field, value
    ):
        line = office_article_line
        before = _office_line_values(line)

        resp = customer_caller_client.patch(
            f"{ORDER_CONTENTS_URL}{line.id}/", {field: value}, format="json"
        )

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["code"] == "order_content.office_only"
        assert resp.data["field"] == field
        assert _office_line_values(line) == before

    def test_the_stored_values_are_accepted(
        self, customer_caller_client, office_article_line
    ):
        """A client that echoes the line sends its values unchanged."""
        line = office_article_line
        before = _office_line_values(line)
        body = {field: getattr(line, field) for field in OFFICE_LINE_CHANGES}

        resp = customer_caller_client.patch(
            f"{ORDER_CONTENTS_URL}{line.id}/",
            {**body, "amount": "10.000"},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert _office_line_values(line) == before

    @pytest.mark.parametrize(
        "offer",
        [
            {"is_finalized": False},
            {"is_finalized": True, "other_group": True},
            {"is_finalized": True, "delivery_week": 16},
        ],
        ids=["draft", "other group", "other week"],
    )
    def test_a_line_on_an_offer_the_page_doesnt_list_is_read_only(
        self, customer_caller_client, customer_caller, offer
    ):
        _u, my_reseller, my_group = customer_caller
        group = OfferGroupFactory() if offer.pop("other_group", False) else my_group
        line = OrderContentFactory(
            order=OrderFactory(reseller=my_reseller),
            offer=OfferFactory(offer_group=group, **offer),
            share_article=None,
            amount=Decimal("10.000"),
        )
        url = f"{ORDER_CONTENTS_URL}{line.id}/"

        changed = customer_caller_client.patch(url, {"amount": "4.000"}, format="json")
        deleted = customer_caller_client.delete(url)

        for resp in (changed, deleted):
            assert resp.status_code == status.HTTP_403_FORBIDDEN
            assert resp.data["code"] == "order_content.office_only"
        line.refresh_from_db()
        assert line.amount == Decimal("10.000")

    def test_a_line_without_offer_is_not_deleted(
        self, customer_caller_client, office_article_line
    ):
        resp = customer_caller_client.delete(
            f"{ORDER_CONTENTS_URL}{office_article_line.id}/"
        )

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["code"] == "order_content.office_only"
        assert OrderContent.objects.filter(pk=office_article_line.pk).exists()

    def test_the_customer_deletes_their_own_line(
        self, customer_caller_client, customer_caller, tiered_offer
    ):
        _u, my_reseller, _g = customer_caller
        body = _page_body(my_reseller, tiered_offer, 2)
        customer_caller_client.post(ORDER_CONTENTS_URL, body, format="json")

        resp = customer_caller_client.delete(
            f"{ORDER_CONTENTS_URL}{_line_of(tiered_offer).id}/"
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert not OrderContent.objects.filter(offer=tiered_offer).exists()

    def test_the_office_changes_a_line_without_offer(
        self, api_client, office_article_line
    ):
        line = office_article_line
        changes = {
            "unit": "KG",
            "size": "L",
            "description": "Basil, 1 kg bunch",
            "sort": "Thai",
            "note": "Free delivery",
        }

        resp = api_client.patch(
            f"{ORDER_CONTENTS_URL}{line.id}/", changes, format="json"
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        line.refresh_from_db()
        assert {field: getattr(line, field) for field in changes} == changes


# --- OrderContentViewSet: the order's days ----------------------------------

SENT_ORDER_DAYS = {
    "harvesting_day": 4,
    "packing_day": 4,
    "washing_day": 4,
    "cleaning_day": 4,
    "last_possible_ordering_day": 6,
}


def _order_days(order):
    order.refresh_from_db()
    return {field: getattr(order, field) for field in SENT_ORDER_DAYS}


@pytest.fixture()
def planned_order(customer_caller):
    """The customer's order of the week, with the days the office set."""
    _u, my_reseller, _g = customer_caller
    return OrderFactory(
        reseller=my_reseller,
        harvesting_day=1,
        packing_day=2,
        washing_day=1,
        cleaning_day=1,
        last_possible_ordering_day=0,
    )


class TestCustomerOrderPageOrderDays:
    """The order's harvesting, washing, cleaning and packing days schedule the
    farm's work for it, and the office sets them and its ordering deadline. The
    customer page sends none; a customer's line that does is saved without
    them."""

    def test_a_customer_line_keeps_the_days_of_an_existing_order(
        self, customer_caller_client, customer_caller, tiered_offer, planned_order
    ):
        _u, my_reseller, _g = customer_caller
        before = _order_days(planned_order)
        body = _page_body(my_reseller, tiered_offer, 6, **SENT_ORDER_DAYS)

        resp = customer_caller_client.post(ORDER_CONTENTS_URL, body, format="json")

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert _line_of(tiered_offer).order_id == planned_order.id
        assert _order_days(planned_order) == before

    def test_a_customer_line_of_a_new_order_takes_the_day_defaults(
        self, customer_caller_client, customer_caller, tiered_offer
    ):
        OrdersDeliveryDay.objects.filter(day_number=2).update(
            default_harvesting_day=1,
            default_packing_day=2,
            default_washing_day=1,
            default_cleaning_day=1,
            default_last_possible_ordering_day=0,
        )
        _u, my_reseller, _g = customer_caller
        body = _page_body(my_reseller, tiered_offer, 6, **SENT_ORDER_DAYS)

        resp = customer_caller_client.post(ORDER_CONTENTS_URL, body, format="json")

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert _order_days(_line_of(tiered_offer).order) == {
            "harvesting_day": 1,
            "packing_day": 2,
            "washing_day": 1,
            "cleaning_day": 1,
            "last_possible_ordering_day": 0,
        }

    def test_the_office_sets_the_days_of_an_existing_order(
        self, api_client, customer_caller, tiered_offer, planned_order
    ):
        _u, my_reseller, _g = customer_caller
        body = _page_body(my_reseller, tiered_offer, 6, **SENT_ORDER_DAYS)

        resp = api_client.post(ORDER_CONTENTS_URL, body, format="json")

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert _order_days(planned_order) == SENT_ORDER_DAYS


# --- OrderContentViewSet: what a customer's line takes from its offer ---------


class TestCustomerOrderPageOfferFields:
    """The goods flow plans a line's harvest, washing, cleaning and storage
    moves from its unit, size, sort and flags. A customer's line takes them
    from its offer, and only its amount and note are the customer's to
    change."""

    def test_a_new_line_takes_them_from_its_offer(
        self, customer_caller_client, customer_caller, tiered_offer
    ):
        _u, my_reseller, _g = customer_caller
        sent = {
            "unit": "BUNCH",
            "size": "L",
            "sort": "Nantes",
            "description": "Bunch",
            "washing": True,
            "cleaning": True,
            "comes_from_long_term_storage": True,
        }
        body = _page_body(my_reseller, tiered_offer, 2, **sent)

        resp = customer_caller_client.post(ORDER_CONTENTS_URL, body, format="json")

        assert resp.status_code == status.HTTP_200_OK, resp.data
        line = _line_of(tiered_offer)
        offer_fields = ("unit", "size", "sort", "washing", "cleaning")
        assert {f: getattr(line, f) for f in offer_fields} == {
            f: getattr(tiered_offer, f) for f in offer_fields
        }
        assert line.comes_from_long_term_storage is False
        assert line.description is None

    def test_a_change_to_them_is_refused(
        self, customer_caller_client, customer_caller, tiered_offer
    ):
        _u, my_reseller, _g = customer_caller
        body = _page_body(my_reseller, tiered_offer, 2)
        customer_caller_client.post(ORDER_CONTENTS_URL, body, format="json")
        url = f"{ORDER_CONTENTS_URL}{_line_of(tiered_offer).id}/"

        changed = customer_caller_client.patch(url, {"unit": "PCS"}, format="json")
        resent = customer_caller_client.patch(url, {"unit": "KG"}, format="json")

        assert changed.status_code == status.HTTP_403_FORBIDDEN
        assert changed.data["code"] == "order_content.office_only"
        assert changed.data["field"] == "unit"
        assert resent.status_code == status.HTTP_200_OK, resent.data
        assert _line_of(tiered_offer).unit == "KG"

    def test_its_note_is_the_customers(
        self, customer_caller_client, customer_caller, tiered_offer
    ):
        _u, my_reseller, _g = customer_caller
        body = _page_body(my_reseller, tiered_offer, 2)
        customer_caller_client.post(ORDER_CONTENTS_URL, body, format="json")

        resp = customer_caller_client.patch(
            f"{ORDER_CONTENTS_URL}{_line_of(tiered_offer).id}/",
            {"note": "Ring twice"},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert _line_of(tiered_offer).note == "Ring twice"


# --- OrderContentViewSet: when a customer's ordering closes ------------------


def _local(*parts):
    """A time on the farm's clock: ``time_machine`` takes a naive one as UTC."""
    return timezone.make_aware(datetime.datetime(*parts))


def _set_deadline(order_day, last_day, last_time=None):
    order_day.default_last_possible_ordering_day = last_day
    order_day.default_last_possible_ordering_time = last_time
    order_day.save()


@pytest.fixture()
def customer_line(customer_caller, tiered_offer):
    """A customer's line of 4 kg on their order for day 2 of week 15."""
    _u, my_reseller, _g = customer_caller
    return OrderContentFactory(
        order=OrderFactory(reseller=my_reseller),
        offer=tiered_offer,
        share_article=None,
        amount=Decimal("4.000"),
        price_per_unit=Decimal("2.00"),
    )


def _writes(client, reseller, line, offer):
    """A new line of ``offer``, an amount change of ``line`` and its delete."""
    url = f"{ORDER_CONTENTS_URL}{line.id}/"
    return (
        client.post(ORDER_CONTENTS_URL, _page_body(reseller, offer, 2), format="json"),
        client.patch(url, {"amount": "6.000"}, format="json"),
        client.delete(url),
    )


class TestCustomerOrderingCloses:
    """The customer page closes a week once it lies before the current one, and
    the delivery day's ordering once its deadline has passed: the deadline's
    weekday of the order's week, at its minute or else at the day's end. The
    server refuses a customer's writes then. Week 15 of 2026 starts on Monday,
    6 April."""

    @pytest.fixture()
    def other_offer(self, customer_caller):
        _u, _r, my_group = customer_caller
        return OfferFactory(offer_group=my_group, is_finalized=True)

    def test_a_past_week_is_closed(
        self, customer_caller_client, customer_caller, customer_line, other_offer
    ):
        _u, my_reseller, _g = customer_caller

        with time_machine.travel(_local(2026, 4, 13, 12, 0), tick=False):
            writes = _writes(
                customer_caller_client, my_reseller, customer_line, other_offer
            )

        for resp in writes:
            assert resp.status_code == status.HTTP_409_CONFLICT
            assert resp.data["code"] == "commissioning.past_week"
        customer_line.refresh_from_db()
        assert customer_line.amount == Decimal("4.000")
        assert not OrderContent.objects.filter(offer=other_offer).exists()

    def test_the_current_week_stays_open(
        self, customer_caller_client, customer_caller, customer_line, other_offer
    ):
        _u, my_reseller, _g = customer_caller

        with time_machine.travel(_local(2026, 4, 12, 23, 0), tick=False):
            writes = _writes(
                customer_caller_client, my_reseller, customer_line, other_offer
            )

        for resp in writes:
            assert resp.status_code == status.HTTP_200_OK, resp.data

    def test_ordering_closes_after_the_deadline_minute(
        self,
        customer_caller_client,
        customer_caller,
        customer_line,
        other_offer,
        order_day,
    ):
        _u, my_reseller, _g = customer_caller
        _set_deadline(order_day, 0, datetime.time(10, 30, 59))
        url = f"{ORDER_CONTENTS_URL}{customer_line.id}/"

        with time_machine.travel(_local(2026, 4, 6, 10, 30), tick=False):
            on_time = customer_caller_client.patch(
                url, {"amount": "8.000"}, format="json"
            )
        with time_machine.travel(_local(2026, 4, 6, 10, 31), tick=False):
            late = _writes(
                customer_caller_client, my_reseller, customer_line, other_offer
            )

        assert on_time.status_code == status.HTTP_200_OK, on_time.data
        for resp in late:
            assert resp.status_code == status.HTTP_409_CONFLICT
            assert resp.data["code"] == "order.ordering_deadline_passed"
        customer_line.refresh_from_db()
        assert customer_line.amount == Decimal("8.000")

    def test_without_a_time_the_deadline_day_stays_open(
        self, customer_caller_client, customer_line, order_day
    ):
        _set_deadline(order_day, 1)
        url = f"{ORDER_CONTENTS_URL}{customer_line.id}/"

        with time_machine.travel(_local(2026, 4, 7, 23, 59), tick=False):
            on_time = customer_caller_client.patch(
                url, {"amount": "8.000"}, format="json"
            )
        with time_machine.travel(_local(2026, 4, 8, 0, 0), tick=False):
            late = customer_caller_client.patch(
                url, {"amount": "10.000"}, format="json"
            )

        assert on_time.status_code == status.HTTP_200_OK, on_time.data
        assert late.status_code == status.HTTP_409_CONFLICT
        assert late.data["code"] == "order.ordering_deadline_passed"

    def test_a_day_without_orders_takes_no_new_line(
        self, customer_caller_client, customer_caller, tiered_offer
    ):
        _u, my_reseller, _g = customer_caller
        body = _page_body(my_reseller, tiered_offer, 2, day_number=3)

        resp = customer_caller_client.post(ORDER_CONTENTS_URL, body, format="json")

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "order.day_not_offered"
        assert resp.data["field"] == "day_number"
        assert not OrderContent.objects.filter(offer=tiered_offer).exists()

    @pytest.mark.parametrize(
        "day, expected",
        [(2, status.HTTP_200_OK), (6, status.HTTP_400_BAD_REQUEST)],
        ids=["Wednesday", "Sunday"],
    )
    def test_without_order_days_monday_to_saturday_are_open(
        self, customer_caller_client, customer_caller, tiered_offer, day, expected
    ):
        """The page's day picker offers Monday to Saturday, with no deadline,
        while the farm has set up no order delivery day."""
        _u, my_reseller, _g = customer_caller
        OrdersDeliveryDay.objects.all().delete()
        body = _page_body(my_reseller, tiered_offer, 2, day_number=day)

        resp = customer_caller_client.post(ORDER_CONTENTS_URL, body, format="json")

        assert resp.status_code == expected, resp.data
        if expected == status.HTTP_400_BAD_REQUEST:
            assert resp.data["code"] == "order.day_not_offered"

    def test_the_office_writes_a_closed_order(
        self, api_client, customer_caller, customer_line, other_offer
    ):
        _u, my_reseller, _g = customer_caller

        with time_machine.travel(_local(2026, 4, 13, 12, 0), tick=False):
            writes = _writes(api_client, my_reseller, customer_line, other_offer)

        for resp in writes:
            assert resp.status_code == status.HTTP_200_OK, resp.data


# --- CrateOrderContent -----------------------------------------------------

CRATE_PERIOD = {"year": 2026, "delivery_week": 15, "day_number": 2}
CRATE_CONTENTS_URL = "/api/commissioning/crate_contents/"


@pytest.fixture()
def own_crate_line(customer_caller):
    """A crate row added to the customer's own order on the office's crate tab."""
    _u, my_reseller, _g = customer_caller
    order = OrderFactory(reseller=my_reseller, **CRATE_PERIOD)
    crate = CrateFactory()
    row = CrateOrderContent.objects.create(
        order=order,
        crate_type=crate,
        amount=2,
        price_per_unit=Decimal("2.50"),
        tax_rate=Decimal("19.00"),
    )
    return SimpleNamespace(order=order, crate=crate, row=row)


def _write_crate_line(client, line, verb):
    """Create, update or delete a crate line of ``line``'s order, at a price
    that would credit the reseller."""
    period = {**CRATE_PERIOD, "reseller": str(line.order.reseller_id)}
    detail_url = f"{CRATE_CONTENTS_URL}{line.crate.id}_{line.row.pk}/"
    if verb == "create":
        body = {**period, "crate_type": str(line.crate.id), "amount": 5}
        return client.post(
            CRATE_CONTENTS_URL, {**body, "price_per_unit": "-50.00"}, format="json"
        )
    if verb == "update":
        body = {**period, "price_per_unit": "0.01", "rabatt": 100}
        return client.patch(detail_url, body, format="json")
    query = urlencode({**period, "order_id": line.order.id})
    return client.delete(f"{detail_url}?{query}")


def _crate_rows(order):
    return list(
        CrateOrderContent.objects.filter(order=order).values_list(
            "pk", "amount", "price_per_unit", "rabatt"
        )
    )


class TestCustomerOrderPage_CrateScoping:
    def test_list_for_other_reseller_forbidden(
        self, customer_caller_client, other_reseller
    ):
        resp = customer_caller_client.get(
            f"/api/commissioning/crate_contents/?year=2026"
            f"&delivery_week=15&day_number=2&reseller={other_reseller.id}"
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.parametrize("verb", ["create", "update", "delete"])
    def test_own_crate_lines_are_not_writable(
        self, customer_caller_client, own_crate_line, verb
    ):
        before = _crate_rows(own_crate_line.order)

        resp = _write_crate_line(customer_caller_client, own_crate_line, verb)

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert _crate_rows(own_crate_line.order) == before

    @pytest.mark.parametrize(
        "verb, expected",
        [
            ("create", status.HTTP_201_CREATED),
            ("update", status.HTTP_200_OK),
            ("delete", status.HTTP_204_NO_CONTENT),
        ],
    )
    def test_the_office_writes_the_same_lines(
        self, api_client, own_crate_line, verb, expected
    ):
        before = _crate_rows(own_crate_line.order)

        resp = _write_crate_line(api_client, own_crate_line, verb)

        assert resp.status_code == expected, resp.data
        assert _crate_rows(own_crate_line.order) != before


# --- DeliveryNote / Invoice (read-own only) -------------------------------


class TestCustomerOrderPage_DocumentsScoping:
    def test_delivery_notes_list_scoped_to_own(
        self, customer_caller_client, customer_caller, other_reseller
    ):
        _u, my_reseller, _g = customer_caller
        mine = DeliveryNoteResellerFactory(
            order=OrderFactory(reseller=my_reseller), is_finalized=True
        )
        foreign = DeliveryNoteResellerFactory(
            order=OrderFactory(reseller=other_reseller), is_finalized=True
        )

        resp = customer_caller_client.get("/api/commissioning/delivery_notes/")
        assert resp.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in resp.data}
        assert mine.id in ids
        assert foreign.id not in ids

    def test_a_draft_delivery_note_and_its_lines_are_hidden(
        self, customer_caller_client, customer_caller
    ):
        _u, my_reseller, _g = customer_caller
        draft = DeliveryNoteResellerFactory(order=OrderFactory(reseller=my_reseller))
        DeliveryNoteContentFactory(delivery_note=draft)
        published = DeliveryNoteResellerFactory(
            order=OrderFactory(reseller=my_reseller, delivery_week=16)
        )
        published_line = DeliveryNoteContentFactory(delivery_note=published)
        DeliveryNoteReseller.objects.filter(pk=published.pk).update(is_finalized=True)

        draft_resp = customer_caller_client.get(
            f"/api/commissioning/delivery_notes/{draft.id}/"
        )
        draft_lines = customer_caller_client.get(
            "/api/commissioning/delivery_note_contents/",
            {"delivery_note_id": draft.id},
        )
        published_lines = customer_caller_client.get(
            "/api/commissioning/delivery_note_contents/",
            {"delivery_note_id": published.id},
        )

        assert draft_resp.status_code == status.HTTP_404_NOT_FOUND
        assert draft_lines.status_code == status.HTTP_200_OK
        assert draft_lines.data == []
        assert [row["id"] for row in published_lines.data] == [published_line.id]

    def test_a_draft_invoice_and_its_lines_are_hidden(
        self, customer_caller_client, customer_caller
    ):
        _u, my_reseller, _g = customer_caller
        draft = InvoiceResellerFactory(reseller=my_reseller)
        published = InvoiceResellerFactory(reseller=my_reseller)
        for invoice in (draft, published):
            InvoiceResellerContent.objects.create(
                invoice=invoice,
                share_article=ShareArticleFactory(),
                amount=Decimal("10.000"),
                unit="KG",
                size="M",
                tax_rate=Decimal("7.00"),
            )
        InvoiceReseller.objects.filter(pk=published.pk).update(is_finalized=True)

        draft_resp = customer_caller_client.get(
            f"/api/commissioning/invoices/{draft.id}/"
        )
        published_resp = customer_caller_client.get(
            f"/api/commissioning/invoices/{published.id}/"
        )
        draft_lines = customer_caller_client.get(
            "/api/commissioning/invoice_contents/", {"invoice_id": draft.id}
        )
        published_lines = customer_caller_client.get(
            "/api/commissioning/invoice_contents/", {"invoice_id": published.id}
        )

        assert draft_resp.status_code == status.HTTP_404_NOT_FOUND
        assert published_resp.status_code == status.HTTP_200_OK
        assert draft_lines.data == []
        assert len(published_lines.data) == 1

    def test_delivery_note_create_forbidden(self, customer_caller_client):
        # write_permission = IsOffice
        resp = customer_caller_client.post(
            "/api/commissioning/delivery_notes/", {}, format="json"
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_invoices_create_forbidden(self, customer_caller_client):
        resp = customer_caller_client.post(
            "/api/commissioning/invoices/", {}, format="json"
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# --- Cross-domain isolation: customer must NOT see member data ------------


class TestCustomer_CannotAccessMemberEndpoints:
    def test_members_list_forbidden(self, customer_caller_client, tenant):
        MemberFactory()
        resp = customer_caller_client.get("/api/commissioning/members/")
        # Customer has no `member` role -> blocked by IsOfficeOrMember.
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_share_delivery_list_forbidden(self, customer_caller_client, tenant):
        resp = customer_caller_client.get(
            "/api/commissioning/share_delivery/?year=2026"
        )
        # ShareDelivery requires IsStaffOrMember.
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_abos_list_forbidden(self, customer_caller_client, tenant):
        resp = customer_caller_client.get("/api/commissioning/abos/")
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# --- OfferViewSet: amount_ordered annotation must not leak a peer's totals -----


class TestCustomerOrderPage_OfferAnnotationScoping:
    URL = "/api/commissioning/offers/"

    def test_customer_cannot_request_peer_reseller_amounts(
        self, customer_caller_client, customer_caller
    ):
        # A peer reseller in the SAME offer group. Passing ?reseller=<peer> would
        # annotate the offers with the peer's per-article ordered volume — an
        # IDOR the endpoint must reject for a non-privileged customer.
        _u, _my_reseller, my_group = customer_caller
        peer = ResellerFactory(offer_group=my_group)

        resp = customer_caller_client.get(
            self.URL, {"year": 2026, "delivery_week": 15, "reseller": peer.id}
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_customer_omitting_reseller_sees_only_own_amounts(
        self, customer_caller_client, customer_caller
    ):
        # With ?reseller= omitted, amount_ordered must reflect ONLY the caller's
        # own reseller (0) — summing the whole group's orders would leak a
        # peer's 42.
        _u, _my_reseller, my_group = customer_caller
        peer = ResellerFactory(offer_group=my_group)
        offer = OfferFactory(
            offer_group=my_group, year=2026, delivery_week=15, is_finalized=True
        )
        peer_order = OrderFactory(reseller=peer, year=2026, delivery_week=15)
        # OrderContent references exactly one item type — the offer (not a free
        # share_article), so it joins the annotation via its ``offer`` FK.
        OrderContentFactory(
            order=peer_order, offer=offer, share_article=None, amount=Decimal("42.000")
        )

        resp = customer_caller_client.get(self.URL, {"year": 2026, "delivery_week": 15})
        assert resp.status_code == status.HTTP_200_OK
        rows = [r for r in resp.data if r["id"] == offer.id]
        assert rows, resp.data
        assert Decimal(rows[0]["amount_ordered"]) == Decimal("0")
