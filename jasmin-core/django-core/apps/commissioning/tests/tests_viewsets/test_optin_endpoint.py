"""Permission / scoping tests for the on-off opt-in endpoints.

The interesting bits:
  * Office can read any member's pending list and toggle on their behalf.
  * Members can read + toggle their OWN deliveries.
  * Members CANNOT read another member's pending list — even by
    passing ``?member=<other_id>``. Same for the toggle (handled by
    ``get_object`` scoping on the queryset).
"""

from __future__ import annotations

import datetime

import pytest
import time_machine
from rest_framework.test import APIClient

from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    JasminUserFactory,
    MemberFactory,
    ShareDeliveryFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)

PENDING_URL = "/api/commissioning/share_delivery/pending_optin/"


def _toggle_url(delivery_id: str) -> str:
    return f"/api/commissioning/share_delivery/{delivery_id}/toggle_optin/"


def _get_or_make_delivery_day():
    """Reuse a single Wednesday SDD across calls in the same test.

    ``SharesDeliveryDay`` carries a TimeBoundMixin overlap check on
    ``day_number``, so two separate factory chains both spinning up
    ``day_number=2`` collide. See the matching helper in
    ``tests_services/test_optin_service.py``.
    """
    from apps.commissioning.models import SharesDeliveryDay

    existing = SharesDeliveryDay.objects.filter(day_number=2).first()
    if existing is not None:
        return existing
    return SharesDeliveryDayFactory(day_number=2)


def _get_or_make_station_day(delivery_day):
    from apps.commissioning.models import DeliveryStationDay

    existing = DeliveryStationDay.objects.filter(delivery_day=delivery_day).first()
    if existing is not None:
        return existing
    return DeliveryStationDayFactory(delivery_day=delivery_day)


def _make_member_with_onoff_delivery(*, requires_optin: bool = True):
    user = JasminUserFactory(roles=["member"])
    member = MemberFactory(user=user)
    variation = ShareTypeVariationFactory(
        requires_optin=requires_optin,
        default_optin_state=False,
        optin_deadline_days_before_delivery=3,
    )
    delivery_day = _get_or_make_delivery_day()
    station_day = _get_or_make_station_day(delivery_day)
    share = ShareFactory(share_type_variation=variation, delivery_day=delivery_day)
    sub = SubscriptionFactory(
        member=member,
        share_type_variation=variation,
        default_delivery_station_day=station_day,
        valid_from=datetime.date(2026, 1, 5),
        valid_until=datetime.date(2026, 12, 27),
    )
    delivery = ShareDeliveryFactory(
        share=share, subscription=sub, delivery_station_day=station_day
    )
    return member, delivery, user


@pytest.mark.django_db
class TestPendingOptinEndpoint:
    def test_office_can_read_any_members_list(self, tenant, api_client):
        owner, _delivery, _ = _make_member_with_onoff_delivery()
        response = api_client.get(PENDING_URL, {"member": str(owner.pk)})
        assert response.status_code == 200

    def test_member_can_read_own_list_via_member_param(self, tenant):
        owner, _delivery, owner_user = _make_member_with_onoff_delivery()
        client = APIClient()
        client.force_authenticate(user=owner_user)
        response = client.get(PENDING_URL, {"member": str(owner.pk)})
        assert response.status_code == 200

    def test_member_can_read_own_list_without_member_param(self, tenant):
        owner, _delivery, owner_user = _make_member_with_onoff_delivery()
        client = APIClient()
        client.force_authenticate(user=owner_user)
        response = client.get(PENDING_URL)
        assert response.status_code == 200

    def test_member_cannot_read_another_members_list(self, tenant):
        """Permission leak guard: a non-office member passing
        ``?member=<other_id>`` must be refused."""
        _other, _other_delivery, _ = _make_member_with_onoff_delivery()
        attacker_user = JasminUserFactory(roles=["member"])
        MemberFactory(user=attacker_user)
        client = APIClient()
        client.force_authenticate(user=attacker_user)
        response = client.get(PENDING_URL, {"member": str(_other.pk)})
        assert response.status_code == 403


@pytest.mark.django_db
class TestToggleOptinEndpoint:
    """HTTP contract for the toggle action — the service rules are unit-tested
    in ``tests_services/test_optin_service.py``; here we lock the endpoint
    wiring (permission/scoping, request parsing, error→status mapping).

    The on-off delivery lands at W15 2026 (Wed 2026-04-08); with a 3-day
    deadline the lock flips on 2026-04-06, so ``time_machine`` pins the day on
    either side. ``format="json"`` so ``opt_in`` arrives as a real bool (a
    multipart POST would stringify it and trip the bool guard → 400)."""

    @time_machine.travel(datetime.datetime(2026, 4, 4, 10, 0, tzinfo=datetime.UTC))
    def test_member_can_toggle_own(self, tenant):
        owner, delivery, owner_user = _make_member_with_onoff_delivery()
        client = APIClient()
        client.force_authenticate(user=owner_user)
        response = client.post(
            _toggle_url(str(delivery.pk)), {"opt_in": True}, format="json"
        )
        assert response.status_code == 200
        delivery.refresh_from_db()
        assert delivery.is_opted_in is True
        assert delivery.optin_decided_by == owner_user

    @time_machine.travel(datetime.datetime(2026, 4, 4, 10, 0, tzinfo=datetime.UTC))
    def test_office_can_toggle_on_behalf(self, tenant, api_client):
        _owner, delivery, _ = _make_member_with_onoff_delivery()
        response = api_client.post(
            _toggle_url(str(delivery.pk)), {"opt_in": True}, format="json"
        )
        assert response.status_code == 200
        delivery.refresh_from_db()
        assert delivery.is_opted_in is True

    def test_member_cannot_toggle_another_members_delivery(self, tenant):
        """Cross-member write guard: scope_to_member hides the row, so
        get_object 404s (no silent toggle, no 403 existence leak)."""
        _owner, delivery, _ = _make_member_with_onoff_delivery()
        attacker_user = JasminUserFactory(roles=["member"])
        MemberFactory(user=attacker_user)
        client = APIClient()
        client.force_authenticate(user=attacker_user)
        response = client.post(
            _toggle_url(str(delivery.pk)), {"opt_in": True}, format="json"
        )
        assert response.status_code == 404
        delivery.refresh_from_db()
        assert delivery.is_opted_in is False

    @time_machine.travel(datetime.datetime(2026, 4, 6, 10, 0, tzinfo=datetime.UTC))
    def test_toggle_after_deadline_returns_409(self, tenant, api_client):
        _owner, delivery, _ = _make_member_with_onoff_delivery()
        response = api_client.post(
            _toggle_url(str(delivery.pk)), {"opt_in": True}, format="json"
        )
        assert response.status_code == 409

    def test_toggle_non_onoff_variation_returns_400(self, tenant, api_client):
        # requires_optin checked before the deadline → 400 regardless of date.
        _owner, delivery, _ = _make_member_with_onoff_delivery(requires_optin=False)
        response = api_client.post(
            _toggle_url(str(delivery.pk)), {"opt_in": True}, format="json"
        )
        assert response.status_code == 400

    @time_machine.travel(datetime.datetime(2026, 4, 4, 10, 0, tzinfo=datetime.UTC))
    def test_toggle_missing_opt_in_returns_400(self, tenant, api_client):
        _owner, delivery, _ = _make_member_with_onoff_delivery()
        response = api_client.post(_toggle_url(str(delivery.pk)), {}, format="json")
        assert response.status_code == 400
