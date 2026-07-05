"""Waiting-list offer flow: office offers a freed spot, member accepts/declines
via magic link, and an offered/accepted spot HOLDS capacity so it can't be
sniped during the response window.

The station-day reservation + the offer email are mocked here — this suite
covers the offer state machine and the variation status-counted hold. The DSD
reservation itself is covered by ``test_capacity_reservation.py``.
"""

from __future__ import annotations

import datetime
from unittest import mock

import pytest
from django.utils import timezone

from apps.commissioning.errors import (
    WaitingListOfferExpired,
    WaitingListOfferInvalid,
    WaitingListOfferNotAvailable,
)
from apps.commissioning.models import Subscription
from apps.commissioning.services.variation_capacity_service import (
    VariationCapacityService,
)
from apps.commissioning.services.waiting_list_offer_service import (
    WaitingListOfferService,
)
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)

_SPAN = {
    "valid_from": datetime.date(2026, 1, 5),  # Monday
    "valid_until": datetime.date(2027, 1, 3),  # Sunday
}


@pytest.fixture
def dsd():
    return DeliveryStationDayFactory()


@pytest.fixture(autouse=True)
def _mock_holds_and_email():
    """Isolate the offer state machine: stub the DSD reservation (own suite) and
    the deferred email so tests don't need harvest/DSD capacity or SMTP."""
    with (
        mock.patch.object(
            WaitingListOfferService, "_send_offer_email", return_value=None
        ),
        mock.patch(
            "apps.commissioning.services.waiting_list_offer_service."
            "CapacityReservationService.reserve_for_subscription",
            return_value=None,
        ),
        mock.patch(
            "apps.commissioning.services.waiting_list_offer_service."
            "CapacityReservationService.release_for_subscription",
            return_value=None,
        ),
    ):
        yield


def _pending(variation, dsd, quantity=1):
    return SubscriptionFactory(
        share_type_variation=variation,
        default_delivery_station_day=dsd,
        quantity=quantity,
        admin_confirmed=False,
        on_waiting_list=True,
        waiting_list_status=Subscription.WaitingListStatus.PENDING,
        **_SPAN,
    )


@pytest.mark.django_db
class TestWaitingListOffer:
    def test_offer_requires_pending_entry(self, tenant, dsd):
        variation = ShareTypeVariationFactory(capacity=5)
        # An ordinary (non-waiting_list) draft can't be offered.
        sub = SubscriptionFactory(
            share_type_variation=variation,
            default_delivery_station_day=dsd,
            admin_confirmed=False,
            **_SPAN,
        )
        with pytest.raises(WaitingListOfferNotAvailable):
            WaitingListOfferService.offer_spot(sub)

    def test_offer_sets_spot_available_with_token(self, tenant, dsd):
        variation = ShareTypeVariationFactory(capacity=5)
        sub = _pending(variation, dsd)
        WaitingListOfferService.offer_spot(sub)
        sub.refresh_from_db()
        assert sub.waiting_list_status == Subscription.WaitingListStatus.SPOT_AVAILABLE
        assert sub.on_waiting_list is True
        assert sub.notification_token is not None
        assert sub.notification_expires_at is not None

    def test_offer_holds_the_variation_slot(self, tenant, dsd):
        # cap 1, nothing confirmed → free. Offering the last slot must HOLD it,
        # so a fresh subscribe now reads the variation as full.
        variation = ShareTypeVariationFactory(capacity=1)
        queued = _pending(variation, dsd)
        WaitingListOfferService.offer_spot(queued)

        newcomer = SubscriptionFactory(
            share_type_variation=variation,
            default_delivery_station_day=dsd,
            admin_confirmed=True,
            **_SPAN,
        )
        assert VariationCapacityService.is_over_capacity(newcomer) is True

    def test_offer_applies_office_price(self, tenant, dsd):
        from decimal import Decimal

        variation = ShareTypeVariationFactory(capacity=5)
        sub = _pending(variation, dsd)
        WaitingListOfferService.offer_spot(sub, price_per_delivery="12.50")
        sub.refresh_from_db()
        assert sub.price_per_delivery == Decimal("12.50")

    def test_accept_leaves_waiting_list_as_unconfirmed_draft(self, tenant, dsd):
        variation = ShareTypeVariationFactory(capacity=5)
        sub = _pending(variation, dsd)
        WaitingListOfferService.offer_spot(sub)
        token = Subscription.objects.get(pk=sub.pk).notification_token

        WaitingListOfferService.accept_offer(token)
        sub.refresh_from_db()
        assert sub.waiting_list_status == Subscription.WaitingListStatus.CONFIRMED
        assert sub.on_waiting_list is False
        assert sub.admin_confirmed is False  # still needs office admin-confirm
        assert sub.notification_token is None  # link consumed

    def test_accepted_pending_still_holds_the_slot(self, tenant, dsd):
        variation = ShareTypeVariationFactory(capacity=1)
        sub = _pending(variation, dsd)
        WaitingListOfferService.offer_spot(sub)
        token = Subscription.objects.get(pk=sub.pk).notification_token
        WaitingListOfferService.accept_offer(
            token
        )  # now CONFIRMED, not admin-confirmed

        newcomer = SubscriptionFactory(
            share_type_variation=variation,
            default_delivery_station_day=dsd,
            admin_confirmed=True,
            **_SPAN,
        )
        assert VariationCapacityService.is_over_capacity(newcomer) is True

    def test_decline_frees_the_slot(self, tenant, dsd):
        variation = ShareTypeVariationFactory(capacity=1)
        sub = _pending(variation, dsd)
        WaitingListOfferService.offer_spot(sub)
        token = Subscription.objects.get(pk=sub.pk).notification_token

        WaitingListOfferService.decline_offer(token)
        sub.refresh_from_db()
        assert sub.waiting_list_status == Subscription.WaitingListStatus.DECLINED
        assert sub.on_waiting_list is False

        newcomer = SubscriptionFactory(
            share_type_variation=variation,
            default_delivery_station_day=dsd,
            admin_confirmed=True,
            **_SPAN,
        )
        assert VariationCapacityService.is_over_capacity(newcomer) is False

    def test_accept_after_window_raises_and_expires(self, tenant, dsd):
        variation = ShareTypeVariationFactory(capacity=5)
        sub = _pending(variation, dsd)
        WaitingListOfferService.offer_spot(sub)
        # Backdate the window so the offer has lapsed.
        # A real lapsed offer keeps sent_at <= expires_at (both in the past);
        # backdate both so the mixin's clean() stays valid on the expiry save.
        Subscription.objects.filter(pk=sub.pk).update(
            notification_sent_at=timezone.now() - datetime.timedelta(days=8),
            notification_expires_at=timezone.now() - datetime.timedelta(days=1),
        )
        token = Subscription.objects.get(pk=sub.pk).notification_token
        with pytest.raises(WaitingListOfferExpired):
            WaitingListOfferService.accept_offer(token)
        sub.refresh_from_db()
        assert sub.waiting_list_status == Subscription.WaitingListStatus.EXPIRED

    def test_unknown_token_is_invalid(self, tenant):
        import uuid

        with pytest.raises(WaitingListOfferInvalid):
            WaitingListOfferService.accept_offer(uuid.uuid4())

    def test_expire_stale_offers_sweep(self, tenant, dsd):
        variation = ShareTypeVariationFactory(capacity=5)
        sub = _pending(variation, dsd)
        WaitingListOfferService.offer_spot(sub)
        # A real lapsed offer keeps sent_at <= expires_at (both in the past);
        # backdate both so the mixin's clean() stays valid on the expiry save.
        Subscription.objects.filter(pk=sub.pk).update(
            notification_sent_at=timezone.now() - datetime.timedelta(days=8),
            notification_expires_at=timezone.now() - datetime.timedelta(days=1),
        )
        assert WaitingListOfferService.expire_stale_offers() == 1
        sub.refresh_from_db()
        assert sub.waiting_list_status == Subscription.WaitingListStatus.EXPIRED
