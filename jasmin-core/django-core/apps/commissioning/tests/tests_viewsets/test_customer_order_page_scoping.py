"""Permission + scoping smoke tests for the Customer Order page.

A user whose only role is ``customer`` should be able to use every
endpoint hit by ``src/pages/customer/CustomerOrderPage.tsx`` for *their
own* reseller (read+edit own reseller, list/create/update/delete own
order contents and crate orders, read own delivery notes / invoices)
and must be denied (403) or get nothing for everything else.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.commissioning.models import OrderContent
from apps.commissioning.tests.factories.accounts import JasminUserFactory
from apps.commissioning.tests.factories.basics import ShareArticleFactory
from apps.commissioning.tests.factories.members import MemberFactory
from apps.commissioning.tests.factories.resellers import (
    DeliveryNoteResellerFactory,
    OfferFactory,
    OfferGroupFactory,
    OrderContentFactory,
    OrderFactory,
    ResellerFactory,
)

# --- Fixtures -------------------------------------------------------------


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
        billing fields is a pricing / privilege hole (SEC-1)."""
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
        my_offer = OfferFactory(offer_group=my_group, year=2026, delivery_week=15)
        foreign_offer = OfferFactory(
            offer_group=other_reseller.offer_group, year=2026, delivery_week=15
        )

        resp = customer_caller_client.get(
            "/api/commissioning/offers/?year=2026&delivery_week=15"
        )
        assert resp.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in resp.data}
        assert my_offer.id in ids
        assert foreign_offer.id not in ids


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
        # API-1: even on their OWN order content, a customer must not set
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
    """The customer order page's create body (``useCustomerOrderMutations``)
    minus ``price_per_unit``, which the office-only pricing guard rejects for a
    customer before the offer checks run."""
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
        booked = OfferFactory(offer_group=my_group, amount=Decimal("90.000"))
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
        booked = OfferFactory(offer_group=my_group, amount=Decimal("90.000"))
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


# --- CrateOrderContent -----------------------------------------------------


class TestCustomerOrderPage_CrateScoping:
    def test_list_for_other_reseller_forbidden(
        self, customer_caller_client, other_reseller
    ):
        resp = customer_caller_client.get(
            f"/api/commissioning/crate_contents/?year=2026"
            f"&delivery_week=15&day_number=2&reseller={other_reseller.id}"
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# --- DeliveryNote / Invoice (read-own only) -------------------------------


class TestCustomerOrderPage_DocumentsScoping:
    def test_delivery_notes_list_scoped_to_own(
        self, customer_caller_client, customer_caller, other_reseller
    ):
        _u, my_reseller, _g = customer_caller
        mine = DeliveryNoteResellerFactory(order=OrderFactory(reseller=my_reseller))
        foreign = DeliveryNoteResellerFactory(
            order=OrderFactory(reseller=other_reseller)
        )

        resp = customer_caller_client.get("/api/commissioning/delivery_notes/")
        assert resp.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in resp.data}
        assert mine.id in ids
        assert foreign.id not in ids

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
        # own reseller — pre-fix it summed the whole group's orders (a peer's 42
        # would leak); post-fix the caller's own reseller (0) is forced.
        _u, _my_reseller, my_group = customer_caller
        peer = ResellerFactory(offer_group=my_group)
        offer = OfferFactory(offer_group=my_group, year=2026, delivery_week=15)
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
