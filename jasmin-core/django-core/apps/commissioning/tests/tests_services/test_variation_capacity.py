"""Tests for the farm-wide ShareTypeVariation production cap.

The production-axis twin of the delivery-station-day capacity (that one is
tested in ``test_capacity_reservation.py``).
"""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.commissioning.errors import ShareTypeVariationOverCapacity
from apps.commissioning.models import Subscription
from apps.commissioning.serializers.shares_serializer import (
    ShareTypeVariationSerializer,
)
from apps.commissioning.services.subscription_service import SubscriptionService
from apps.commissioning.services.variation_capacity_service import (
    VariationCapacityService,
)
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)

# A term that covers "today" (the session clock) so live subs are counted.
# Subscriptions require a Monday valid_from + a Sunday valid_until.
_SPAN = {
    "valid_from": datetime.date(2026, 1, 5),  # Monday
    "valid_until": datetime.date(2027, 1, 3),  # Sunday
}


@pytest.fixture
def dsd():
    # One shared, capacity-less delivery-station-day for a test's subscriptions:
    # each SubscriptionFactory would otherwise spawn its own DSD (+ open
    # SharesDeliveryDay) and trip the "one open per day" constraint. Variation
    # capacity is independent of the DSD, so a single shared one is fine.
    return DeliveryStationDayFactory()


def _confirmed(variation, dsd, quantity=1, **extra):
    span = {
        **_SPAN,
        **{k: extra.pop(k) for k in ("valid_from", "valid_until") if k in extra},
    }
    extra.setdefault("admin_confirmed", True)
    return SubscriptionFactory(
        share_type_variation=variation,
        default_delivery_station_day=dsd,
        quantity=quantity,
        **span,
        **extra,
    )


@pytest.mark.django_db
class TestVariationCapacity:
    def test_occupied_capacity_sums_live_confirmed_quantity(self, tenant, dsd):
        variation = ShareTypeVariationFactory(capacity=20)
        _confirmed(variation, dsd, quantity=3)
        _confirmed(variation, dsd, quantity=2)
        # NOT counted: draft (unconfirmed), cancelled, waiting_listed.
        _confirmed(variation, dsd, quantity=5, admin_confirmed=False)
        _confirmed(variation, dsd, quantity=5, cancelled_at=timezone.now())
        _confirmed(variation, dsd, quantity=5, on_waiting_list=True)
        assert variation.get_occupied_capacity() == 5

    def test_assert_raises_when_new_sub_would_exceed(self, tenant, dsd):
        variation = ShareTypeVariationFactory(capacity=3)
        _confirmed(variation, dsd, quantity=3)
        new = _confirmed(variation, dsd, quantity=1)
        with pytest.raises(ShareTypeVariationOverCapacity):
            VariationCapacityService.assert_capacity_available(new)

    def test_assert_passes_under_cap(self, tenant, dsd):
        variation = ShareTypeVariationFactory(capacity=5)
        _confirmed(variation, dsd, quantity=2)
        new = _confirmed(variation, dsd, quantity=1)
        VariationCapacityService.assert_capacity_available(new)  # no raise

    def test_ample_capacity_never_blocks(self, tenant, dsd):
        variation = ShareTypeVariationFactory(capacity=1000)
        _confirmed(variation, dsd, quantity=99)
        new = _confirmed(variation, dsd, quantity=99)
        VariationCapacityService.assert_capacity_available(new)  # no raise

    def test_non_overlapping_terms_do_not_count(self, tenant, dsd):
        variation = ShareTypeVariationFactory(capacity=1)
        # An existing sub whose term ends BEFORE the new one begins — no overlap
        # (both within the variation's open window from 2026-01-05).
        _confirmed(
            variation,
            dsd,
            quantity=1,
            valid_from=datetime.date(2026, 1, 5),  # Monday
            valid_until=datetime.date(2026, 6, 28),  # Sunday
        )
        new = _confirmed(
            variation,
            dsd,
            quantity=1,
            valid_from=datetime.date(2026, 7, 6),  # Monday, after the above ends
            valid_until=datetime.date(2027, 1, 3),  # Sunday
        )
        VariationCapacityService.assert_capacity_available(new)  # no raise

    def test_peak_week_counts_concurrency_not_total_overlap(self, tenant, dsd):
        # Two existing subs each overlap the new sub's term but NOT each other
        # (sequential halves). Concurrent occupancy is therefore only 1 in any
        # single week — the old "sum every overlapping sub" model counted 2 and
        # wrongly blocked. Peak-week must let this through.
        variation = ShareTypeVariationFactory(capacity=2)
        _confirmed(
            variation,
            dsd,
            quantity=1,
            valid_from=datetime.date(2026, 1, 5),  # Monday
            valid_until=datetime.date(2026, 6, 28),  # Sunday
        )
        _confirmed(
            variation,
            dsd,
            quantity=1,
            valid_from=datetime.date(2026, 7, 6),  # Monday, after the first ends
            valid_until=datetime.date(2027, 1, 3),  # Sunday
        )
        new = _confirmed(variation, dsd, quantity=1)  # spans the whole year
        VariationCapacityService.assert_capacity_available(new)  # no raise

    def test_peak_week_blocks_when_subs_are_concurrent(self, tenant, dsd):
        # Same cap=2, but now both existing subs run the FULL term → concurrent
        # occupancy is 2 every week, so the peak week is full.
        variation = ShareTypeVariationFactory(capacity=2)
        _confirmed(variation, dsd, quantity=1)
        _confirmed(variation, dsd, quantity=1)
        new = _confirmed(variation, dsd, quantity=1)
        with pytest.raises(ShareTypeVariationOverCapacity):
            VariationCapacityService.assert_capacity_available(new)

    def test_serializer_exposes_free_and_occupied(self, tenant, dsd):
        variation = ShareTypeVariationFactory(capacity=10)
        _confirmed(variation, dsd, quantity=4)
        data = ShareTypeVariationSerializer(variation).data
        assert data["capacity_occupied"] == 4
        assert data["capacity_free"] == 6

    def _serialize_with_window(
        self, variation, year=2026, delivery_week=1, num_weeks=104
    ):
        request = APIRequestFactory().get(
            "/",
            {"year": year, "delivery_week": delivery_week, "num_weeks": num_weeks},
        )
        return ShareTypeVariationSerializer(
            variation, context={"request": Request(request)}
        ).data

    def test_capacity_by_week_is_none_without_window(self, tenant, dsd):
        # No year/delivery_week on the request → the term-aware field stays null
        # (only the flat today-snapshot fields are populated).
        variation = ShareTypeVariationFactory(capacity=5)
        data = ShareTypeVariationSerializer(variation).data
        assert data["capacity_by_week"] is None

    def test_capacity_by_week_marks_full_weeks_within_the_term(self, tenant, dsd):
        # A single confirmed sub filling the cap for the whole _SPAN
        # (2026-01-05 → 2027-01-03) makes every week IT covers full (free 0),
        # while weeks outside its term stay free. ISO week keys are unpadded
        # ("2026-2"), matching the station-day serializer.
        variation = ShareTypeVariationFactory(capacity=5)
        _confirmed(variation, dsd, quantity=5)
        by_week = self._serialize_with_window(variation)["capacity_by_week"]
        # 2026-01-05 (valid_from, Monday) is ISO week 2 of 2026 → full.
        assert by_week["2026-2"]["occupied"] == 5
        assert by_week["2026-2"]["free"] == 0
        # ISO week 1 (2025-12-29 → 2026-01-04) predates the term → empty.
        assert by_week["2026-1"]["occupied"] == 0
        assert by_week["2026-1"]["free"] == 5

    def test_waiting_list_reason_variation_full(self, tenant, dsd):
        variation = ShareTypeVariationFactory(capacity=1)
        _confirmed(variation, dsd, quantity=1)  # fills the cap
        queued = _confirmed(variation, dsd, quantity=1, on_waiting_list=True)
        reason = SubscriptionService._infer_waiting_list_reason(queued)
        assert reason == Subscription.WaitingListReason.VARIATION_FULL

    def test_waiting_list_reason_manual_when_nothing_full(self, tenant, dsd):
        # Ample variation capacity + an unfilled station-day: neither gate is
        # full, so a queued sub reflects a manual office decision.
        variation = ShareTypeVariationFactory(capacity=1000)
        queued = _confirmed(variation, dsd, quantity=1, on_waiting_list=True)
        reason = SubscriptionService._infer_waiting_list_reason(queued)
        assert reason == Subscription.WaitingListReason.MANUAL
