"""DeliveryExceptionPeriod ("Lieferpause") wiring.

Covers the two levers:
* the subscription generation path skips paused weeks (no ShareDelivery, hence
  no demand / billing), and
* create/delete resync brings ALREADY-confirmed subscriptions in line (future
  weeks only).

Plus the serializer's whole-week / non-overlap validation.
"""

from __future__ import annotations

import datetime

import pytest
import time_machine

from apps.commissioning.models import (
    DeliveryExceptionPeriod,
    ShareDelivery,
    Subscription,
)
from apps.commissioning.serializers import DeliveryExceptionPeriodSerializer
from apps.commissioning.services.delivery_exceptions import (
    paused_weeks_for_variation,
    resync_delivery_exception,
    weeks_in_range,
)
from apps.commissioning.services.subscription_service import SubscriptionService
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    SharesDeliveryDayFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)
from apps.commissioning.tests.factories.members import PaymentCycleFactory

# A subscription term spanning four future delivery weeks (all Mondays/Sundays
# after today = 2026-07-01 so the "future weeks only" resync touches them all).
_VALID_FROM = datetime.date(2026, 7, 6)  # Monday, ISO week 28
_VALID_UNTIL = datetime.date(2026, 8, 2)  # Sunday, ISO week 31
# A pause covering the first two of those weeks.
_PAUSE_FROM = datetime.date(2026, 7, 6)  # Monday, week 28
_PAUSE_UNTIL = datetime.date(2026, 7, 19)  # Sunday, week 29
# A pause that has already started/ended (before today = 2026-07-01).
_PAST_FROM = datetime.date(2026, 6, 15)  # Monday
_PAST_UNTIL = datetime.date(2026, 6, 28)  # Sunday


def _variation():
    return ShareTypeVariationFactory(
        share_type=ShareTypeFactory(share_option="HARVEST_SHARE")
    )


def _materialised_subscription(variation, *, confirmed: bool = True) -> Subscription:
    delivery_day = SharesDeliveryDayFactory(day_number=2)  # Wednesday
    dsd = DeliveryStationDayFactory(delivery_day=delivery_day)
    subscription = SubscriptionFactory(
        share_type_variation=variation,
        default_delivery_station_day=dsd,
        valid_from=_VALID_FROM,
        valid_until=_VALID_UNTIL,
        quantity=1,
        payment_cycle=PaymentCycleFactory(),
    )
    SubscriptionService().materialize_confirmed_subscription(subscription)
    if confirmed:
        # Stamp confirmation without re-running full_clean (the resync filters
        # on admin_confirmed=True).
        Subscription.objects.filter(pk=subscription.pk).update(admin_confirmed=True)
    return subscription


def _delivered_weeks(subscription: Subscription) -> set[tuple[int, int]]:
    return {
        (share_delivery.share.year, share_delivery.share.delivery_week)
        for share_delivery in ShareDelivery.objects.filter(
            subscription=subscription
        ).select_related("share")
    }


# ═══════════════════════════════════════════════════════
# Pure helpers
# ═══════════════════════════════════════════════════════


class TestWeeksHelpers:
    def test_weeks_in_range_covers_each_whole_week(self):
        weeks = weeks_in_range(_PAUSE_FROM, _PAUSE_UNTIL)
        # Two ISO weeks: the Monday's week and the following week.
        assert weeks == {
            _PAUSE_FROM.isocalendar()[:2],
            (_PAUSE_FROM + datetime.timedelta(days=7)).isocalendar()[:2],
        }
        assert len(weeks) == 2

    def test_weeks_in_range_empty_when_open_ended(self):
        assert weeks_in_range(_PAUSE_FROM, None) == set()

    @pytest.mark.django_db
    def test_paused_weeks_for_variation_matches_only_covered_weeks(self, tenant):
        variation = _variation()
        DeliveryExceptionPeriod.objects.create(
            share_type_variation=variation,
            valid_from=_PAUSE_FROM,
            valid_until=_PAUSE_UNTIL,
        )
        term_weeks = weeks_in_range(_VALID_FROM, _VALID_UNTIL)
        paused = paused_weeks_for_variation(variation.id, term_weeks)
        assert paused == weeks_in_range(_PAUSE_FROM, _PAUSE_UNTIL)
        assert paused < term_weeks  # a proper subset — later weeks stay open


# ═══════════════════════════════════════════════════════
# Generation path: new subscriptions skip paused weeks
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestGenerationPathSkipsPausedWeeks:
    def test_no_share_delivery_is_materialised_for_a_paused_week(self, tenant):
        variation = _variation()
        DeliveryExceptionPeriod.objects.create(
            share_type_variation=variation,
            valid_from=_PAUSE_FROM,
            valid_until=_PAUSE_UNTIL,
        )

        subscription = _materialised_subscription(variation, confirmed=False)

        delivered = _delivered_weeks(subscription)
        paused = weeks_in_range(_PAUSE_FROM, _PAUSE_UNTIL)
        assert delivered, "some weeks should still be delivered"
        assert not (delivered & paused), "paused weeks must have no ShareDelivery"
        # The non-paused weeks of the term ARE delivered.
        assert delivered == weeks_in_range(_VALID_FROM, _VALID_UNTIL) - paused

    def test_resolve_station_days_excludes_paused_weeks(self, tenant):
        """Capacity paths derive weeks from resolve_station_days_by_week — it
        must skip paused weeks too, else they reserve/count phantom occupancy for
        weeks that get no ShareDelivery."""
        variation = _variation()
        subscription = _materialised_subscription(variation, confirmed=False)

        before = set(
            SubscriptionService.resolve_station_days_by_week(subscription).keys()
        )
        assert before, "baseline: some weeks resolve to a station-day"

        DeliveryExceptionPeriod.objects.create(
            share_type_variation=variation,
            valid_from=_PAUSE_FROM,
            valid_until=_PAUSE_UNTIL,
        )
        after = set(
            SubscriptionService.resolve_station_days_by_week(subscription).keys()
        )
        paused = weeks_in_range(_PAUSE_FROM, _PAUSE_UNTIL)
        assert not (after & paused), "paused weeks must not consume a station-day slot"
        assert after == before - paused


# ═══════════════════════════════════════════════════════
# Resync of already-confirmed subscriptions
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestResyncConfirmedSubscriptions:
    @time_machine.travel(datetime.date(2026, 7, 1), tick=False)
    def test_create_pause_deletes_future_deliveries_in_paused_weeks(self, tenant):
        variation = _variation()
        subscription = _materialised_subscription(variation)
        term_weeks = weeks_in_range(_VALID_FROM, _VALID_UNTIL)
        assert _delivered_weeks(subscription) == term_weeks

        # Create the pause AFTER confirmation, then resync (mirrors the viewset's
        # perform_create).
        DeliveryExceptionPeriod.objects.create(
            share_type_variation=variation,
            valid_from=_PAUSE_FROM,
            valid_until=_PAUSE_UNTIL,
        )
        paused = weeks_in_range(_PAUSE_FROM, _PAUSE_UNTIL)
        resync_delivery_exception(
            share_type_variation_id=variation.id,
            newly_paused_weeks=paused,
            freed_weeks=set(),
        )

        assert _delivered_weeks(subscription) == term_weeks - paused

    @time_machine.travel(datetime.date(2026, 7, 1), tick=False)
    def test_delete_pause_restores_freed_deliveries(self, tenant):
        variation = _variation()
        subscription = _materialised_subscription(variation)
        term_weeks = weeks_in_range(_VALID_FROM, _VALID_UNTIL)
        paused = weeks_in_range(_PAUSE_FROM, _PAUSE_UNTIL)

        # Pause then unpause.
        resync_delivery_exception(
            share_type_variation_id=variation.id,
            newly_paused_weeks=paused,
            freed_weeks=set(),
        )
        assert _delivered_weeks(subscription) == term_weeks - paused

        resync_delivery_exception(
            share_type_variation_id=variation.id,
            newly_paused_weeks=set(),
            freed_weeks=paused,
        )
        assert _delivered_weeks(subscription) == term_weeks

    def test_resync_ignores_unconfirmed_subscriptions(self, tenant):
        variation = _variation()
        subscription = _materialised_subscription(variation, confirmed=False)
        term_weeks = weeks_in_range(_VALID_FROM, _VALID_UNTIL)

        resync_delivery_exception(
            share_type_variation_id=variation.id,
            newly_paused_weeks=weeks_in_range(_PAUSE_FROM, _PAUSE_UNTIL),
            freed_weeks=set(),
        )
        # An unconfirmed subscription is left untouched by the resync.
        assert _delivered_weeks(subscription) == term_weeks


# ═══════════════════════════════════════════════════════
# Serializer validation
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestSerializerValidation:
    def test_valid_until_is_required(self, tenant):
        """An open-ended pause suppresses nothing (weeks_in_range(from, None) is
        empty) and would break paused_weeks_for_variation — the API must reject
        a missing valid_until even though the model field is nullable."""
        variation = _variation()
        serializer = DeliveryExceptionPeriodSerializer(
            data={
                "share_type_variation": str(variation.id),
                "valid_from": "2026-07-06",  # Monday, no valid_until
            }
        )
        assert not serializer.is_valid()
        assert "valid_until" in serializer.errors

    def test_valid_from_must_be_monday(self, tenant):
        from apps.commissioning.errors import DeliveryExceptionInvalidRange

        variation = _variation()
        serializer = DeliveryExceptionPeriodSerializer(
            data={
                "share_type_variation": str(variation.id),
                "valid_from": "2026-07-07",  # Tuesday
                "valid_until": "2026-07-19",
            }
        )
        with pytest.raises(DeliveryExceptionInvalidRange):
            serializer.is_valid(raise_exception=True)

    def test_overlapping_period_is_rejected(self, tenant):
        from apps.commissioning.errors import DeliveryExceptionOverlap

        variation = _variation()
        DeliveryExceptionPeriod.objects.create(
            share_type_variation=variation,
            valid_from=_PAUSE_FROM,
            valid_until=_PAUSE_UNTIL,
        )
        serializer = DeliveryExceptionPeriodSerializer(
            data={
                "share_type_variation": str(variation.id),
                "valid_from": "2026-07-13",  # inside the existing pause
                "valid_until": "2026-07-26",
            }
        )
        with pytest.raises(DeliveryExceptionOverlap):
            serializer.is_valid(raise_exception=True)

    def test_non_overlapping_period_validates(self, tenant):
        variation = _variation()
        DeliveryExceptionPeriod.objects.create(
            share_type_variation=variation,
            valid_from=_PAUSE_FROM,
            valid_until=_PAUSE_UNTIL,
        )
        serializer = DeliveryExceptionPeriodSerializer(
            data={
                "share_type_variation": str(variation.id),
                "valid_from": "2026-07-20",  # Monday, after the existing pause
                "valid_until": "2026-07-26",  # Sunday
            }
        )
        assert serializer.is_valid(), serializer.errors


# ═══════════════════════════════════════════════════════
# Active/past periods are frozen (unchangeable + undeletable)
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestActivePastPeriodsAreLocked:
    @staticmethod
    def _started_period(variation):
        # Bypass the serializer (which forbids past valid_from) to seed a period
        # that has already started/ended relative to today.
        return DeliveryExceptionPeriod.objects.create(
            share_type_variation=variation,
            valid_from=_PAST_FROM,
            valid_until=_PAST_UNTIL,
        )

    # Freeze "today" before _PAUSE_FROM (2026-07-06) so the has-started /
    # locking checks stay date-relative regardless of wall-clock drift.
    @time_machine.travel(datetime.date(2026, 7, 1), tick=False)
    def test_has_started_helper(self, tenant):
        variation = _variation()
        future = DeliveryExceptionPeriod(
            share_type_variation=variation,
            valid_from=_PAUSE_FROM,
            valid_until=_PAUSE_UNTIL,
        )
        past = DeliveryExceptionPeriod(
            share_type_variation=variation,
            valid_from=_PAST_FROM,
            valid_until=_PAST_UNTIL,
        )
        assert not future.has_started()
        assert past.has_started()

    def test_started_period_cannot_be_edited(self, tenant):
        from apps.commissioning.errors import DeliveryExceptionPeriodLocked

        started = self._started_period(_variation())
        serializer = DeliveryExceptionPeriodSerializer(
            instance=started, data={"note": "changed"}, partial=True
        )
        with pytest.raises(DeliveryExceptionPeriodLocked):
            serializer.is_valid(raise_exception=True)

    def test_started_period_cannot_be_deleted(self, tenant):
        from apps.commissioning.errors import DeliveryExceptionPeriodLocked
        from apps.commissioning.viewsets.delivery_viewsets import (
            DeliveryExceptionPeriodViewSet,
        )

        started = self._started_period(_variation())
        with pytest.raises(DeliveryExceptionPeriodLocked):
            DeliveryExceptionPeriodViewSet().perform_destroy(started)
        assert DeliveryExceptionPeriod.objects.filter(pk=started.pk).exists()

    def test_creating_a_past_period_is_rejected(self, tenant):
        from apps.commissioning.errors import DeliveryExceptionInvalidRange

        variation = _variation()
        serializer = DeliveryExceptionPeriodSerializer(
            data={
                "share_type_variation": str(variation.id),
                "valid_from": _PAST_FROM.isoformat(),
                "valid_until": _PAST_UNTIL.isoformat(),
            }
        )
        with pytest.raises(DeliveryExceptionInvalidRange):
            serializer.is_valid(raise_exception=True)

    @time_machine.travel(datetime.date(2026, 7, 1), tick=False)
    def test_future_period_stays_editable(self, tenant):
        variation = _variation()
        future = DeliveryExceptionPeriod.objects.create(
            share_type_variation=variation,
            valid_from=_PAUSE_FROM,
            valid_until=_PAUSE_UNTIL,
        )
        serializer = DeliveryExceptionPeriodSerializer(
            instance=future, data={"note": "changed"}, partial=True
        )
        assert serializer.is_valid(), serializer.errors
        assert future.has_started() is False
