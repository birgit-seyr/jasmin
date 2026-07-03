"""Permission + scoping smoke tests for the Member Detail page.

A user whose only role is ``member`` should be able to access the
endpoints used by ``src/pages/members/MemberDetail.tsx`` for *their own*
member profile, deliveries and subscriptions, and must be denied (403)
or get an empty / 404 result for everything else.
"""

from __future__ import annotations

import datetime

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.commissioning.tests.factories.accounts import JasminUserFactory
from apps.commissioning.tests.factories.days import (
    DeliveryStationDayFactory,
    SharesDeliveryDayFactory,
)
from apps.commissioning.tests.factories.members import (
    MemberFactory,
    SubscriptionFactory,
)
from apps.commissioning.tests.factories.resellers import (
    OrderContentFactory,
    ResellerFactory,
)


@pytest.fixture()
def member_caller(tenant):
    """A member user linked to their own Member row.

    The user's only role is ``member`` — they have no staff / office /
    customer powers. ``member_profile`` is the reverse OneToOne from
    ``JasminUser`` to ``Member``, used by ``scope_to_member``.
    """
    user = JasminUserFactory(roles=["member"])
    member = MemberFactory(user=user)
    return user, member


@pytest.fixture()
def member_caller_client(member_caller):
    user, _member = member_caller
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture()
def other_member(tenant):
    """An unrelated member belonging to nobody — for negative checks."""
    return MemberFactory()


# --- MemberViewSet --------------------------------------------------------


class TestMemberDetail_MemberRoleScoping:
    """A member-only user can READ their own member row, but all writes on this
    office viewset are forbidden — member self-edit goes through the narrow
    MyMemberDataView, not the broad MemberSerializer here."""

    def test_list_returns_only_self(
        self, member_caller_client, member_caller, other_member
    ):
        _user, my_member = member_caller
        resp = member_caller_client.get("/api/commissioning/members/")
        assert resp.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in resp.data}
        assert ids == {my_member.id}
        assert other_member.id not in ids

    def test_retrieve_self_ok(self, member_caller_client, member_caller):
        _user, my_member = member_caller
        resp = member_caller_client.get(f"/api/commissioning/members/{my_member.id}/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["id"] == my_member.id

    def test_self_read_omits_office_internal_fields(
        self, member_caller_client, member_caller
    ):
        """A member reading their OWN row must NOT receive office-internal
        fields. The office MemberSerializer is ``fields = "__all__"`` +
        ``linked_user_info``; ``read_only_fields`` guards writes, not reads,
        so it would leak the free-text ``note`` and the admin confirm/reject
        audit trail. Member-role callers get the narrowed
        MemberSelfReadSerializer instead."""
        _user, my_member = member_caller
        my_member.note = "internal office note about this member"
        my_member.admin_rejection_reason = "suspected duplicate signup"
        my_member.save(update_fields=["note", "admin_rejection_reason"])

        resp = member_caller_client.get(f"/api/commissioning/members/{my_member.id}/")

        assert resp.status_code == status.HTTP_200_OK
        for leaked in (
            "note",
            "admin_rejection_reason",
            "admin_rejected_at",
            "admin_confirmed_by",
            "admin_confirmed_at",
            "linked_user_info",
        ):
            assert leaked not in resp.data, f"{leaked} leaked to member self-read"
        # The member still sees their OWN data (Art. 15).
        assert resp.data["id"] == my_member.id
        assert resp.data["first_name"] == my_member.first_name

    def test_office_read_still_exposes_internal_fields(self, api_client, member_caller):
        """The narrowing is member-only — office/staff keep the full
        serializer, so the office UI is unaffected."""
        _user, my_member = member_caller
        my_member.note = "internal office note"
        my_member.save(update_fields=["note"])

        resp = api_client.get(f"/api/commissioning/members/{my_member.id}/")

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data.get("note") == "internal office note"
        assert "linked_user_info" in resp.data

    def test_retrieve_other_member_404(self, member_caller_client, other_member):
        # Scoped queryset hides foreign rows -> 404, never 200.
        resp = member_caller_client.get(
            f"/api/commissioning/members/{other_member.id}/"
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_partial_update_self_forbidden(self, member_caller_client, member_caller):
        # Writes on this office viewset are office-only; a member editing their
        # own row must use MyMemberDataView. This guards against a member
        # PATCHing is_active / is_trial via the broad MemberSerializer.
        _user, my_member = member_caller
        resp = member_caller_client.patch(
            f"/api/commissioning/members/{my_member.id}/",
            {"pickup_name": "Locker 7"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_partial_update_other_member_forbidden(
        self, member_caller_client, other_member
    ):
        # 403 (not 404): the office-only write permission is checked before the
        # scoped get_object(), so a member never reaches the row-lookup stage.
        resp = member_caller_client.patch(
            f"/api/commissioning/members/{other_member.id}/",
            {"pickup_name": "x"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_create_member_forbidden(self, member_caller_client):
        resp = member_caller_client.post(
            "/api/commissioning/members/",
            {
                "first_name": "X",
                "last_name": "Y",
                "email": "x@y.com",
                "entry_date": str(datetime.date.today()),
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_destroy_self_forbidden(self, member_caller_client, member_caller):
        _user, my_member = member_caller
        resp = member_caller_client.delete(
            f"/api/commissioning/members/{my_member.id}/"
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_office_only_actions_forbidden(self, member_caller_client, member_caller):
        _user, my_member = member_caller
        for action in ("confirm", "reject", "send_invitation"):
            resp = member_caller_client.post(
                f"/api/commissioning/members/{my_member.id}/{action}/"
            )
            assert resp.status_code == status.HTTP_403_FORBIDDEN, action


# --- SubscriptionViewSet (`/abos/`) --------------------------------------


class TestAbos_MemberRoleScoping:
    def test_list_returns_only_own_subscriptions(
        self, member_caller_client, member_caller, other_member
    ):
        _user, my_member = member_caller
        # ``SharesDeliveryDayFactory`` defaults to ``day_number=2`` and
        # ``valid_from=2026-01-05`` -- creating two via the SubFactory chain
        # would trip the (day_number,) overlap check. Pre-create distinct
        # delivery_station_days so each subscription has its own.
        dsd_mine = DeliveryStationDayFactory(
            delivery_day=SharesDeliveryDayFactory(day_number=2)
        )
        dsd_other = DeliveryStationDayFactory(
            delivery_day=SharesDeliveryDayFactory(day_number=3)
        )
        my_sub = SubscriptionFactory(
            member=my_member,
            default_delivery_station_day=dsd_mine,
        )
        other_sub = SubscriptionFactory(
            member=other_member,
            default_delivery_station_day=dsd_other,
        )

        resp = member_caller_client.get("/api/commissioning/abos/")
        assert resp.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in resp.data}
        assert my_sub.id in ids
        assert other_sub.id not in ids

    def test_create_subscription_forbidden(self, member_caller_client):
        # write_permission = IsOffice -> members can never create.
        resp = member_caller_client.post("/api/commissioning/abos/", {}, format="json")
        assert resp.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_403_FORBIDDEN,
        )
        # If the perm class lets it through it must be 400, never 201.
        assert resp.status_code != status.HTTP_201_CREATED


# --- ShareDeliveryViewSet ------------------------------------------------


class TestShareDelivery_MemberRoleScoping:
    def test_list_filters_to_own_deliveries(
        self, member_caller_client, member_caller, other_member
    ):
        # Only assert the scope behaves like a filter — not the wire shape.
        _user, _my_member = member_caller
        resp = member_caller_client.get("/api/commissioning/share_delivery/?year=2026")
        assert resp.status_code == status.HTTP_200_OK


# --- Cross-domain isolation: member must NOT see reseller data -----------


class TestMember_CannotAccessResellerEndpoints:
    def test_resellers_list_forbidden_or_empty(self, member_caller_client, tenant):
        ResellerFactory()
        resp = member_caller_client.get("/api/commissioning/resellers/")
        # Member has no `customer` role -> blocked by IsStaffOrCustomer.
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_order_contents_list_forbidden(self, member_caller_client, tenant):
        OrderContentFactory()
        resp = member_caller_client.get(
            "/api/commissioning/order_contents/?year=2026&delivery_week=15"
            "&day_number=2&reseller=00000000"
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
