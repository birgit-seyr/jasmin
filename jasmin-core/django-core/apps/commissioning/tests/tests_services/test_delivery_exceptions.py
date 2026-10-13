"""DeliveryExceptionPeriod ("Lieferpause") wiring.

Covers the two levers:
* the subscription generation path skips paused weeks (no ShareDelivery, hence
  no demand / billing), and
* create/delete resync brings ALREADY-confirmed subscriptions in line (future
  weeks only, and never past a cancellation's effective date).

Plus the serializer's whole-week / non-overlap validation.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
import time_machine
from django.utils import timezone

from apps.commissioning.models import (
    DeliveryExceptionPeriod,
    ShareDelivery,
    Subscription,
)
from apps.commissioning.serializers import DeliveryExceptionPeriodSerializer
from apps.commissioning.services.delivery_exceptions import (
    paused_weeks_for_variation,
    resync_delivery_exception,
)
from apps.commissioning.services.member_cancellation import (
    _force_end_subscription,
    cancel_member_with_coop_shares,
)
from apps.commissioning.services.subscription_service import SubscriptionService
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    JasminUserFactory,
    MemberFactory,
    SharesDeliveryDayFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)
from apps.commissioning.tests.factories.members import PaymentCycleFactory
from apps.commissioning.utils.iso_week_utils import share_delivery_date, weeks_in_range
from apps.commissioning.viewsets.delivery_viewsets import DeliveryExceptionPeriodViewSet
from apps.payments.constants import ChargeStatus
from apps.payments.models import ChargeSchedule
from apps.shared.tenants.models import TenantSettings

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
    # Pin "now" to the file's reference date (2026-07-01) so the past-week
    # materialisation clamp keeps the fixed term weeks (28–31) future — else it
    # drops weeks that have since fallen behind the wall clock, and the asserted
    # week sets rot.
    @pytest.fixture(autouse=True)
    def _freeze(self):
        with time_machine.travel(datetime.date(2026, 7, 1), tick=False):
            yield

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

    @time_machine.travel(datetime.date(2026, 7, 1), tick=False)
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
# Resync of cancelled subscriptions: the effective term end
# ═══════════════════════════════════════════════════════


def _bill_exactly(tenant) -> None:
    """Bill every delivery in its own period (EXACT), so a delivery restored
    after an exit shows up as a positive PLANNED charge for its period."""
    row = TenantSettings.objects.filter(tenant=tenant, valid_until__isnull=True).first()
    if row is None:
        row = TenantSettings(
            tenant=tenant, valid_from=timezone.now() - datetime.timedelta(days=365)
        )
    elif row.valid_from > timezone.now():
        # The frozen clock sits before a row opened in real time; move its start
        # back so ``get_current_settings`` sees it.
        row.valid_from = timezone.now() - datetime.timedelta(days=365)
    row.billing_strategy = TenantSettings.BILLING_STRATEGY_EXACT
    row.bills_joker_deliveries = False
    row.save()


def _confirmed_subscription(
    variation, station_day, member, **term_fields
) -> Subscription:
    """A confirmed subscription with its deliveries and charges, 10.00 per
    delivery, billed monthly. ``term_fields`` carries ``valid_from`` /
    ``valid_until`` and, for a renewal, ``previous_subscription``."""
    subscription = SubscriptionFactory(
        member=member,
        share_type_variation=variation,
        default_delivery_station_day=station_day,
        quantity=1,
        price_per_delivery=Decimal("10.00"),
        payment_cycle=PaymentCycleFactory(choice="MONTHLY"),
        **term_fields,
    )
    SubscriptionService().materialize_confirmed_subscription(subscription)
    Subscription.objects.filter(pk=subscription.pk).update(admin_confirmed=True)
    subscription.refresh_from_db()
    return subscription


def _create_pause(variation, valid_from, valid_until) -> DeliveryExceptionPeriod:
    """Create a pause the way the office does: serializer, then perform_create."""
    serializer = DeliveryExceptionPeriodSerializer(
        data={
            "share_type_variation": str(variation.id),
            "valid_from": valid_from.isoformat(),
            "valid_until": valid_until.isoformat(),
        }
    )
    serializer.is_valid(raise_exception=True)
    DeliveryExceptionPeriodViewSet().perform_create(serializer)
    return serializer.instance


def _shorten_pause(pause, valid_until) -> None:
    serializer = DeliveryExceptionPeriodSerializer(
        instance=pause, data={"valid_until": valid_until.isoformat()}, partial=True
    )
    serializer.is_valid(raise_exception=True)
    DeliveryExceptionPeriodViewSet().perform_update(serializer)


def _delivery_dates(subscription: Subscription) -> list[datetime.date]:
    return sorted(
        share_delivery_date(share_delivery)
        for share_delivery in ShareDelivery.objects.filter(
            subscription=subscription
        ).select_related("share__delivery_day")
    )


def _positive_planned_charges_after(subscription, day) -> list[ChargeSchedule]:
    """PLANNED charges with an amount to collect for a period starting after
    ``day``. A zero-amount PLANNED row there is expected: the periods still run
    to ``valid_until``."""
    return list(
        ChargeSchedule.objects.filter(
            subscription=subscription,
            status=ChargeStatus.PLANNED,
            period_start__gt=day,
            expected_amount__gt=Decimal("0.00"),
        )
    )


@pytest.mark.django_db
class TestResyncHonoursCancellation:
    """A member exit force-ends a subscription by stamping
    ``cancelled_effective_at`` and leaves ``valid_until`` as it was. Editing a
    pause afterwards must restore nothing after that date — no delivery, no
    charge — while a subscription cancelled with ``cancel_subscription`` keeps
    its pauses suppressed and restored inside its shortened term."""

    # Every week of the terms below starts after "today", so the future-weeks
    # only resync and the past-week clamp of materialisation leave them in.
    @pytest.fixture(autouse=True)
    def _freeze(self):
        with time_machine.travel(datetime.date(2026, 7, 1), tick=False):
            yield

    @pytest.fixture()
    def station_day(self):
        return DeliveryStationDayFactory(
            delivery_day=SharesDeliveryDayFactory(day_number=2)  # Wednesday
        )

    @pytest.fixture()
    def member(self):
        # Joined long before the backdated exit below.
        return MemberFactory(entry_date=datetime.date(2026, 1, 5))

    def test_deleting_a_pause_restores_nothing_for_a_force_ended_renewal(
        self, tenant, station_day, member
    ):
        _bill_exactly(tenant)
        variation = _variation()
        current = _confirmed_subscription(
            variation,
            station_day,
            member=member,
            valid_from=datetime.date(2026, 6, 1),
            valid_until=datetime.date(2026, 7, 5),
        )
        renewal = _confirmed_subscription(
            variation,
            station_day,
            member=member,
            valid_from=_VALID_FROM,
            valid_until=_VALID_UNTIL,
            previous_subscription=current,
        )
        pause = _create_pause(variation, _PAUSE_FROM, _PAUSE_UNTIL)

        # The exit falls before the renewal starts: cancel_subscription can't
        # cancel it, so the exit force-ends it.
        exit_date = datetime.date(2026, 7, 5)
        cancel_member_with_coop_shares(
            member,
            cancelled_effective_at=exit_date,
            cancelled_by=JasminUserFactory(),
            force=True,
        )
        renewal.refresh_from_db()
        assert renewal.cancelled_effective_at == exit_date
        assert renewal.valid_until == _VALID_UNTIL
        assert _delivered_weeks(renewal) == set()

        DeliveryExceptionPeriodViewSet().perform_destroy(pause)

        assert _delivered_weeks(renewal) == set()
        assert _positive_planned_charges_after(renewal, exit_date) == []

    def test_shortening_a_pause_restores_nothing_after_a_backdated_exit(
        self, tenant, station_day, member
    ):
        _bill_exactly(tenant)
        variation = _variation()
        subscription = _confirmed_subscription(
            variation,
            station_day,
            member=member,
            valid_from=datetime.date(2026, 6, 1),
            valid_until=datetime.date(2026, 8, 30),
        )
        pause = _create_pause(
            variation, datetime.date(2026, 7, 20), datetime.date(2026, 8, 16)
        )

        # A backdated exit is already past the next Sunday cancel_subscription
        # accepts, so the exit force-ends the running subscription.
        exit_date = datetime.date(2026, 6, 24)  # a Wednesday
        cancel_member_with_coop_shares(
            member,
            cancelled_effective_at=exit_date,
            cancelled_by=JasminUserFactory(),
            force=True,
        )
        subscription.refresh_from_db()
        assert subscription.cancelled_effective_at == exit_date
        assert subscription.valid_until == datetime.date(2026, 8, 30)
        assert _delivered_weeks(subscription) == set()

        # Weeks 32 and 33 leave the pause; the member left before both.
        _shorten_pause(pause, datetime.date(2026, 8, 2))

        assert _delivered_weeks(subscription) == set()
        assert _positive_planned_charges_after(subscription, exit_date) == []

    def test_a_cancelled_subscription_keeps_its_pauses_inside_its_term(
        self, tenant, station_day, member
    ):
        _bill_exactly(tenant)
        variation = _variation()
        subscription = _confirmed_subscription(
            variation,
            station_day,
            member=member,
            valid_from=_VALID_FROM,
            valid_until=datetime.date(2026, 8, 30),
        )
        effective_at = datetime.date(2026, 8, 16)  # the Sunday of week 33
        SubscriptionService().cancel_subscription(
            subscription, cancelled_by=JasminUserFactory(), effective_at=effective_at
        )
        subscription.refresh_from_db()
        assert subscription.valid_until == subscription.cancelled_effective_at
        kept = weeks_in_range(_VALID_FROM, effective_at)
        assert _delivered_weeks(subscription) == kept

        pause = _create_pause(
            variation, datetime.date(2026, 8, 3), datetime.date(2026, 8, 30)
        )
        assert _delivered_weeks(subscription) == kept - {(2026, 32), (2026, 33)}

        DeliveryExceptionPeriodViewSet().perform_destroy(pause)

        # Weeks 32 and 33 come back; 34 and 35 lie after the cancellation.
        assert _delivered_weeks(subscription) == kept
        assert _positive_planned_charges_after(subscription, effective_at) == []

    @pytest.mark.parametrize(
        ("exit_date", "restored"),
        [
            (datetime.date(2026, 7, 21), set()),  # Tuesday before the delivery
            (datetime.date(2026, 7, 22), {(2026, 30)}),  # the delivery day itself
            (datetime.date(2026, 7, 23), {(2026, 30)}),  # Thursday after it
        ],
    )
    def test_restore_cuts_at_a_mid_week_exit_like_the_force_end(
        self, tenant, station_day, member, exit_date, restored
    ):
        _bill_exactly(tenant)
        variation = _variation()
        subscription = _confirmed_subscription(
            variation,
            station_day,
            member=member,
            valid_from=_VALID_FROM,
            valid_until=datetime.date(2026, 8, 30),
        )
        pause = _create_pause(
            variation, datetime.date(2026, 7, 20), datetime.date(2026, 8, 2)
        )
        _force_end_subscription(
            subscription, effective=exit_date, now=timezone.now(), cancelled_by=None
        )
        before_exit = {(2026, 28), (2026, 29)}
        assert _delivered_weeks(subscription) == before_exit

        DeliveryExceptionPeriodViewSet().perform_destroy(pause)

        # Week 30 delivers on Wednesday 2026-07-22: back only when the exit is
        # on or after that day, the same strict "after the exit" cut the
        # force-end applied. Week 31 (2026-07-29) never comes back.
        assert _delivered_weeks(subscription) == before_exit | restored
        assert max(_delivery_dates(subscription)) <= exit_date
        assert _positive_planned_charges_after(subscription, exit_date) == []


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

    @time_machine.travel(datetime.date(2026, 7, 1), tick=False)
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

    @time_machine.travel(datetime.date(2026, 7, 1), tick=False)
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

    @time_machine.travel(datetime.date(2026, 7, 1), tick=False)
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
