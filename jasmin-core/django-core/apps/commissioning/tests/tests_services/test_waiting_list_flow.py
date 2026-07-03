"""Tests for the per-station-day waiting list on subscriptions.

A draft created with ``on_waiting_list=True`` holds NO capacity (no
reservation, no deliveries) and gets a PENDING status plus the next FIFO
position for its station-day. Promotion is manual: the office confirms the
entry through the normal confirm flow, which re-checks capacity, materialises
the deliveries, and clears the waiting-list state.
"""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone

from apps.commissioning.errors import DeliveryStationOverCapacity
from apps.commissioning.models import (
    CapacityReservation,
    ShareDelivery,
    Subscription,
)
from apps.commissioning.services.subscription_service import SubscriptionService
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    MemberFactory,
    SharesDeliveryDayFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)
from apps.commissioning.tests.factories.members import PaymentCycleFactory

DAY_NUMBER = 2  # Wednesday — matches SharesDeliveryDayFactory default
VALID_FROM = datetime.date(2026, 1, 5)  # Monday
VALID_UNTIL = datetime.date(2026, 1, 11)  # Sunday — a one-week term


def _make_dsd(*, capacity=None, delivery_day=None):
    """One station-day. Pass ``delivery_day`` to put several stations on the
    SAME weekday — creating a second SharesDeliveryDay with the same
    ``day_number`` violates the one-open-per-day-number constraint."""
    if delivery_day is None:
        delivery_day = SharesDeliveryDayFactory(day_number=DAY_NUMBER)
    return DeliveryStationDayFactory(delivery_day=delivery_day, capacity=capacity)


def _occupy_slot(dsd):
    """Hold one slot at ``dsd`` for the test term via an active reservation.
    Returns the reservation so a test can delete it to free the slot."""
    share_type = ShareTypeFactory(share_option="HARVEST_SHARE")
    variation = ShareTypeVariationFactory(share_type=share_type)
    occupier = SubscriptionFactory(
        share_type_variation=variation,
        default_delivery_station_day=dsd,
        valid_from=VALID_FROM,
        valid_until=VALID_UNTIL,
    )
    year, week = SubscriptionService._get_delivery_weeks(
        VALID_FROM, VALID_UNTIL, DAY_NUMBER
    )[0]
    return CapacityReservation.objects.create(
        subscription=occupier,
        delivery_station_day=dsd,
        year=year,
        week=week,
        expires_at=timezone.now() + datetime.timedelta(days=1),
    )


def _validated_data(dsd, *, on_waiting_list=False):
    """Build validated_data the way the serializer hands it over."""
    share_type = ShareTypeFactory(share_option="HARVEST_SHARE")
    variation = ShareTypeVariationFactory(share_type=share_type)
    data = {
        "member": MemberFactory().id,
        "share_type_variation": variation.id,
        "valid_from": VALID_FROM,
        "valid_until": VALID_UNTIL,
        "default_delivery_station_day": dsd,
        "quantity": 1,
        "payment_cycle": PaymentCycleFactory(),
    }
    if on_waiting_list:
        data["on_waiting_list"] = True
    return data


@pytest.mark.django_db
class TestWaitingListCreate:
    def test_waitlisted_create_skips_reservation_and_assigns_position(self, tenant):
        dsd = _make_dsd(capacity=1)
        _occupy_slot(dsd)  # station now full

        subscription = SubscriptionService().create_bare_subscription(
            _validated_data(dsd, on_waiting_list=True)
        )

        assert subscription.on_waiting_list is True
        assert (
            subscription.waiting_list_status == Subscription.WaitingListStatus.PENDING
        )
        assert subscription.waiting_list_position == 1
        # Waitlist entries hold no capacity.
        assert not CapacityReservation.objects.filter(
            subscription=subscription
        ).exists()

    def test_positions_are_fifo_per_station_day(self, tenant):
        shared_weekday = SharesDeliveryDayFactory(day_number=DAY_NUMBER)
        dsd_a = _make_dsd(capacity=1, delivery_day=shared_weekday)
        dsd_b = _make_dsd(capacity=1, delivery_day=shared_weekday)
        _occupy_slot(dsd_a)
        _occupy_slot(dsd_b)

        service = SubscriptionService()
        first = service.create_bare_subscription(
            _validated_data(dsd_a, on_waiting_list=True)
        )
        second = service.create_bare_subscription(
            _validated_data(dsd_a, on_waiting_list=True)
        )
        other_day = service.create_bare_subscription(
            _validated_data(dsd_b, on_waiting_list=True)
        )

        assert first.waiting_list_position == 1
        assert second.waiting_list_position == 2
        # The queue is per station-day, not global.
        assert other_day.waiting_list_position == 1

    def test_normal_create_on_full_station_still_refused(self, tenant):
        dsd = _make_dsd(capacity=1)
        _occupy_slot(dsd)

        with pytest.raises(DeliveryStationOverCapacity):
            SubscriptionService().create_bare_subscription(_validated_data(dsd))


@pytest.mark.django_db
class TestWaitingListPromotion:
    def test_confirm_promotes_when_spot_freed(self, tenant):
        dsd = _make_dsd(capacity=1)
        blocking_hold = _occupy_slot(dsd)
        subscription = SubscriptionService().create_bare_subscription(
            _validated_data(dsd, on_waiting_list=True)
        )

        # The occupier leaves — the slot frees up and the office confirms.
        blocking_hold.delete()
        SubscriptionService().materialize_confirmed_subscription(subscription)

        subscription.refresh_from_db()
        assert subscription.on_waiting_list is False
        assert (
            subscription.waiting_list_status == Subscription.WaitingListStatus.CONFIRMED
        )
        assert subscription.response_received_at is not None
        assert ShareDelivery.objects.filter(subscription=subscription).exists()

    def test_confirm_refused_while_station_still_full(self, tenant):
        dsd = _make_dsd(capacity=1)
        _occupy_slot(dsd)
        subscription = SubscriptionService().create_bare_subscription(
            _validated_data(dsd, on_waiting_list=True)
        )

        with pytest.raises(DeliveryStationOverCapacity):
            SubscriptionService().materialize_confirmed_subscription(subscription)

        subscription.refresh_from_db()
        assert subscription.on_waiting_list is True
        assert (
            subscription.waiting_list_status == Subscription.WaitingListStatus.PENDING
        )
        assert not ShareDelivery.objects.filter(subscription=subscription).exists()


@pytest.mark.django_db
class TestWaitingListDraftUpdate:
    def test_update_keeps_position_and_skips_reservation(self, tenant):
        dsd = _make_dsd(capacity=1)
        _occupy_slot(dsd)
        subscription = SubscriptionService().create_bare_subscription(
            _validated_data(dsd, on_waiting_list=True)
        )

        SubscriptionService().update_draft_subscription(subscription, {"quantity": 2})

        subscription.refresh_from_db()
        assert subscription.quantity == 2
        assert subscription.waiting_list_position == 1
        assert not CapacityReservation.objects.filter(
            subscription=subscription
        ).exists()

    def test_update_requeues_on_station_day_change(self, tenant):
        shared_weekday = SharesDeliveryDayFactory(day_number=DAY_NUMBER)
        dsd_a = _make_dsd(capacity=1, delivery_day=shared_weekday)
        dsd_b = _make_dsd(capacity=1, delivery_day=shared_weekday)
        _occupy_slot(dsd_a)
        _occupy_slot(dsd_b)
        service = SubscriptionService()
        service.create_bare_subscription(
            _validated_data(dsd_b, on_waiting_list=True)
        )  # dsd_b queue: position 1
        moving = service.create_bare_subscription(
            _validated_data(dsd_a, on_waiting_list=True)
        )

        service.update_draft_subscription(
            moving, {"default_delivery_station_day": dsd_b}
        )

        moving.refresh_from_db()
        # Re-queued at the END of the new station-day's list.
        assert moving.waiting_list_position == 2
        assert not CapacityReservation.objects.filter(subscription=moving).exists()
