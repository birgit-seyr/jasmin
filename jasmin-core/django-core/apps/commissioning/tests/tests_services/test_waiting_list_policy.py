"""Server-side enforcement of ``allows_waiting_list_for_subscriptions``.

When the tenant turns the waiting list off, the whole flow is refused
(enqueue, offer, accept/decline). Missing overlay row → default to enabled
(a freshly-provisioned tenant keeps the historical behaviour before its first
config save, matching the model default of ``True``).

Also pins ``reservation_ttl_days`` reading through the same overlay.
"""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone

from apps.commissioning.errors import WaitingListDisabled
from apps.commissioning.services.capacity_reservation_service import (
    RESERVATION_TTL_DAYS,
    _reservation_ttl_days,
)
from apps.commissioning.services.waiting_list_offer_service import (
    WaitingListOfferService,
)
from apps.commissioning.services.waiting_list_policy import (
    assert_waiting_list_enabled,
    waiting_list_enabled,
)
from apps.commissioning.tests.factories import SubscriptionFactory
from apps.shared.tenants.models import TenantSettings


def _make_settings(tenant, **kwargs) -> TenantSettings:
    return TenantSettings.objects.create(
        tenant=tenant,
        valid_from=timezone.now() - datetime.timedelta(seconds=1),
        **kwargs,
    )


@pytest.mark.django_db
class TestWaitingListPolicy:
    def test_no_overlay_defaults_to_enabled(self, tenant):
        assert waiting_list_enabled() is True
        assert_waiting_list_enabled()  # no raise

    def test_enabled_when_flag_on(self, tenant):
        _make_settings(tenant, allows_waiting_list_for_subscriptions=True)
        assert waiting_list_enabled() is True
        assert_waiting_list_enabled()  # no raise

    def test_disabled_when_flag_off(self, tenant):
        _make_settings(tenant, allows_waiting_list_for_subscriptions=False)
        assert waiting_list_enabled() is False
        with pytest.raises(WaitingListDisabled):
            assert_waiting_list_enabled()


@pytest.mark.django_db
class TestReservationTtlDays:
    def test_no_overlay_defaults_to_constant(self, tenant):
        assert _reservation_ttl_days() == RESERVATION_TTL_DAYS

    def test_reads_configured_value(self, tenant):
        _make_settings(tenant, reservation_ttl_days=30)
        assert _reservation_ttl_days() == 30


@pytest.mark.django_db
class TestOfferServiceGate:
    def test_offer_spot_refused_when_disabled(self, tenant):
        _make_settings(tenant, allows_waiting_list_for_subscriptions=False)
        subscription = SubscriptionFactory(on_waiting_list=True)
        with pytest.raises(WaitingListDisabled):
            WaitingListOfferService.offer_spot(subscription)
