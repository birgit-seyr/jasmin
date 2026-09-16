"""Which delivery weeks a confirmed subscription materialises.

By default materialisation (and the capacity paths that share the week list)
never touches delivery weeks before the current week. In normal use
``valid_from`` is a future Monday, so this is a no-op; it matters when a
subscription with a HISTORICAL ``valid_from`` is confirmed.

In onboarding mode a fresh confirm backfills the last
``ONBOARDING_BACKFILL_WEEKS`` weeks (``earliest_monday``). Paused weeks and the
delivery cycle still apply, past weeks resolve to the station day active at the
time, capacity checks keep ignoring past weeks, and the backfilled deliveries
are billed.
"""

from __future__ import annotations

import datetime
import logging
from decimal import Decimal

import pytest
import time_machine
from django.utils import timezone
from isoweek import Week

from apps.commissioning.models import DeliveryExceptionPeriod, ShareDelivery
from apps.commissioning.models.choices import DeliveryCycleOptions
from apps.commissioning.services.onboarding_policy import (
    ONBOARDING_BACKFILL_WEEKS,
    backfill_earliest_monday,
)
from apps.commissioning.services.share_demand_service import ShareDemandService
from apps.commissioning.services.subscription_service import SubscriptionService
from apps.commissioning.services.variation_capacity_service import (
    VariationCapacityService,
)
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    JasminUserFactory,
    MemberFactory,
    PaymentCycleFactory,
    SharesDeliveryDayFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)
from apps.payments.constants import ChargeStatus
from apps.payments.models import ChargeSchedule
from apps.shared.tenants.models import TenantSettings

_FROZEN = datetime.date(2026, 7, 20)  # a Monday, ISO week 30
_CURRENT_MONDAY = Week.withdate(_FROZEN).monday()
_BACKFILL_MONDAY = _CURRENT_MONDAY - datetime.timedelta(weeks=ONBOARDING_BACKFILL_WEEKS)
_SUBSCRIPTION_LOGGER = "apps.commissioning.services.subscription_service"


def _weeks(subscription, **kwargs):
    return SubscriptionService._delivery_weeks_excluding_paused(subscription, **kwargs)


def _monday(weeks_from_now: int) -> datetime.date:
    return _CURRENT_MONDAY + datetime.timedelta(weeks=weeks_from_now)


def _sunday(weeks_from_now: int) -> datetime.date:
    return _monday(weeks_from_now) + datetime.timedelta(days=6)


def _mondays(year_weeks) -> list[datetime.date]:
    return [Week(year, week).monday() for year, week in year_weeks]


def _delivered_mondays(subscription) -> list[datetime.date]:
    return sorted(
        Week(share_delivery.share.year, share_delivery.share.delivery_week).monday()
        for share_delivery in ShareDelivery.objects.filter(
            subscription=subscription
        ).select_related("share")
    )


def _set_tenant_settings(tenant, *, onboarding_mode: bool) -> None:
    row = TenantSettings.objects.filter(tenant=tenant, valid_until__isnull=True).first()
    if row is None:
        row = TenantSettings(
            tenant=tenant, valid_from=timezone.now() - datetime.timedelta(days=365)
        )
    elif row.valid_from > timezone.now():
        # The frozen clock sits before a row opened in real time; move its start
        # back so ``get_current_settings`` sees it.
        row.valid_from = timezone.now() - datetime.timedelta(days=365)
    row.onboarding_mode = onboarding_mode
    row.billing_strategy = TenantSettings.BILLING_STRATEGY_EXACT
    row.bills_joker_deliveries = False
    row.save()


def _draft(variation, station_day, *, valid_from, valid_until):
    """An unconfirmed subscription of an already admitted member, 10.00 per
    delivery, billed monthly."""
    return SubscriptionFactory(
        member=MemberFactory(admin_confirmed=True),
        share_type_variation=variation,
        default_delivery_station_day=station_day,
        valid_from=valid_from,
        valid_until=valid_until,
        quantity=1,
        price_per_delivery=Decimal("10.00"),
        payment_cycle=PaymentCycleFactory(choice="MONTHLY"),
    )


def _station_day_chain():
    """A station day that ended four weeks ago and its open-ended successor
    (same station, same delivery day)."""
    delivery_day = SharesDeliveryDayFactory(day_number=2)
    station = DeliveryStationFactory()
    ended = DeliveryStationDayFactory(
        delivery_station=station,
        delivery_day=delivery_day,
        valid_from=datetime.date(2026, 1, 5),
        valid_until=_sunday(-4),
    )
    successor = DeliveryStationDayFactory(
        delivery_station=station,
        delivery_day=delivery_day,
        valid_from=_monday(-3),
    )
    return ended, successor


@pytest.fixture(autouse=True)
def _freeze():
    with time_machine.travel(_FROZEN, tick=False):
        yield


@pytest.fixture()
def variation(tenant):
    return ShareTypeVariationFactory(
        share_type=ShareTypeFactory(share_option="HARVEST_SHARE")
    )


@pytest.mark.django_db
class TestMaterializePastClamp:
    def test_past_weeks_are_dropped_future_kept(self, tenant):
        # Term straddles "now": 4 weeks in the past → 4 weeks in the future.
        dsd = DeliveryStationDayFactory()
        sub = SubscriptionFactory(
            default_delivery_station_day=dsd,
            valid_from=_FROZEN - datetime.timedelta(weeks=4),  # Monday
            valid_until=_FROZEN + datetime.timedelta(weeks=4, days=6),  # Sunday
        )
        weeks = _weeks(sub)
        assert weeks, "current + future weeks must survive"
        # Every surviving week starts on/after the current week's Monday.
        assert all(Week(y, w).monday() >= _CURRENT_MONDAY for (y, w) in weeks), weeks
        # The oldest past week is gone.
        past = Week.withdate(_FROZEN - datetime.timedelta(weeks=4))
        assert (past.year, past.week) not in weeks
        # The current week is kept.
        cur = Week.withdate(_FROZEN)
        assert (cur.year, cur.week) in weeks

    def test_future_only_term_is_unaffected(self, tenant):
        # valid_from in the future → clamp is a no-op; the whole term survives.
        dsd = DeliveryStationDayFactory()
        start = _FROZEN + datetime.timedelta(weeks=2)  # Monday
        sub = SubscriptionFactory(
            default_delivery_station_day=dsd,
            valid_from=start,
            valid_until=start + datetime.timedelta(weeks=3, days=6),  # Sunday
        )
        weeks = _weeks(sub)
        # 4 weeks, all future, none dropped.
        assert len(weeks) == 4
        assert all(Week(y, w).monday() >= start for (y, w) in weeks)

    def test_entirely_past_term_yields_no_weeks(self, tenant):
        # A term that ended before this week materialises nothing.
        dsd = DeliveryStationDayFactory()
        sub = SubscriptionFactory(
            default_delivery_station_day=dsd,
            valid_from=_FROZEN - datetime.timedelta(weeks=8),  # Monday
            valid_until=_FROZEN - datetime.timedelta(days=1),  # last Sunday
        )
        assert _weeks(sub) == []


@pytest.mark.django_db
class TestEarliestMondayWeekSet:
    def test_no_argument_keeps_the_current_week_floor(self, tenant):
        sub = SubscriptionFactory(
            default_delivery_station_day=DeliveryStationDayFactory(),
            valid_from=_monday(-10),
            valid_until=_sunday(3),
        )
        assert _weeks(sub) == _weeks(sub, earliest_monday=None)
        assert _mondays(_weeks(sub)) == [_monday(n) for n in range(0, 4)]

    def test_backfill_adds_the_past_weeks_back_to_earliest_monday(self, tenant):
        sub = SubscriptionFactory(
            default_delivery_station_day=DeliveryStationDayFactory(),
            valid_from=_monday(-10),
            valid_until=_sunday(3),
        )
        weeks = _weeks(sub, earliest_monday=_BACKFILL_MONDAY)
        # Six past weeks, the current week and three future weeks.
        assert _mondays(weeks) == [_monday(n) for n in range(-6, 4)]

    def test_backfill_never_reaches_before_valid_from(self, tenant):
        sub = SubscriptionFactory(
            default_delivery_station_day=DeliveryStationDayFactory(),
            valid_from=_monday(-3),
            valid_until=_sunday(3),
        )
        weeks = _weeks(sub, earliest_monday=_BACKFILL_MONDAY)
        assert _mondays(weeks) == [_monday(n) for n in range(-3, 4)]

    def test_floor_after_the_current_week_still_keeps_the_current_week(self, tenant):
        sub = SubscriptionFactory(
            default_delivery_station_day=DeliveryStationDayFactory(),
            valid_from=_monday(-10),
            valid_until=_sunday(3),
        )
        assert _weeks(sub, earliest_monday=_monday(2)) == _weeks(sub)

    def test_floor_on_a_weekday_starts_at_that_weeks_monday(self, tenant):
        sub = SubscriptionFactory(
            default_delivery_station_day=DeliveryStationDayFactory(),
            valid_from=_monday(-10),
            valid_until=_sunday(3),
        )
        wednesday = _BACKFILL_MONDAY + datetime.timedelta(days=2)
        assert _weeks(sub, earliest_monday=wednesday) == _weeks(
            sub, earliest_monday=_BACKFILL_MONDAY
        )

    def test_past_paused_weeks_stay_excluded(self, tenant):
        sub = SubscriptionFactory(
            default_delivery_station_day=DeliveryStationDayFactory(),
            valid_from=_monday(-10),
            valid_until=_sunday(3),
        )
        DeliveryExceptionPeriod.objects.create(
            share_type_variation=sub.share_type_variation,
            valid_from=_monday(-4),
            valid_until=_sunday(-3),
        )
        weeks = _weeks(sub, earliest_monday=_BACKFILL_MONDAY)
        assert _mondays(weeks) == [
            _monday(n) for n in range(-6, 4) if n not in (-4, -3)
        ]

    def test_delivery_cycle_parity_holds_for_past_weeks(self, tenant):
        share_type = ShareTypeFactory(
            share_option="HARVEST_SHARE", delivery_cycle=DeliveryCycleOptions.ODD_WEEKS
        )
        assert share_type.delivery_cycle == DeliveryCycleOptions.ODD_WEEKS
        sub = SubscriptionFactory(
            share_type_variation=ShareTypeVariationFactory(share_type=share_type),
            default_delivery_station_day=DeliveryStationDayFactory(),
            valid_from=_monday(-10),  # ISO week 20
            valid_until=_sunday(3),  # ISO week 33
        )
        backfilled = _weeks(sub, earliest_monday=_BACKFILL_MONDAY)
        assert [week for _, week in backfilled] == [25, 27, 29, 31, 33]
        # The current week (30) is even, so the default set starts at week 31.
        assert [week for _, week in _weeks(sub)] == [31, 33]

    def test_past_weeks_resolve_to_the_station_day_active_then(self, tenant):
        ended, successor = _station_day_chain()
        sub = SubscriptionFactory(
            default_delivery_station_day=ended,
            valid_from=_monday(-10),
            valid_until=_sunday(3),
        )
        resolved = SubscriptionService.resolve_station_days_by_week(
            sub, earliest_monday=_BACKFILL_MONDAY
        )
        assert {
            Week(year, week).monday(): station_day.id
            for (year, week), station_day in resolved.items()
        } == {
            **{_monday(n): ended.id for n in range(-6, -3)},
            **{_monday(n): successor.id for n in range(-3, 4)},
        }
        # Without the argument only current and future weeks are resolved.
        assert set(SubscriptionService.resolve_station_days_by_week(sub).values()) == {
            successor
        }


class TestBackfillEarliestMonday:
    def test_is_six_weeks_before_the_current_monday(self):
        assert backfill_earliest_monday() == _BACKFILL_MONDAY

    def test_counts_from_the_monday_of_the_current_week(self):
        thursday = datetime.datetime(2026, 7, 23, 12, 0)
        with time_machine.travel(thursday, tick=False):
            assert backfill_earliest_monday() == _BACKFILL_MONDAY


@pytest.mark.django_db
class TestOnboardingConfirmBackfill:
    def test_flag_off_confirm_materialises_current_and_future_weeks(
        self, tenant, variation
    ):
        _set_tenant_settings(tenant, onboarding_mode=False)
        subscription = _draft(
            variation,
            DeliveryStationDayFactory(),
            valid_from=_monday(-10),
            valid_until=_sunday(3),
        )
        subscription.confirm(admin_user=JasminUserFactory(), save=True)
        assert _delivered_mondays(subscription) == [_monday(n) for n in range(0, 4)]

    def test_flag_on_confirm_backfills_six_weeks(self, tenant, variation):
        _set_tenant_settings(tenant, onboarding_mode=True)
        subscription = _draft(
            variation,
            DeliveryStationDayFactory(),
            valid_from=_monday(-10),
            valid_until=_sunday(3),
        )
        subscription.confirm(admin_user=JasminUserFactory(), save=True)
        assert _delivered_mondays(subscription) == [_monday(n) for n in range(-6, 4)]

    def test_flag_on_past_deliveries_use_the_station_day_active_then(
        self, tenant, variation, caplog
    ):
        _set_tenant_settings(tenant, onboarding_mode=True)
        ended, successor = _station_day_chain()
        subscription = _draft(
            variation, ended, valid_from=_monday(-10), valid_until=_sunday(3)
        )
        with caplog.at_level(logging.ERROR, logger=_SUBSCRIPTION_LOGGER):
            subscription.confirm(admin_user=JasminUserFactory(), save=True)

        station_day_by_monday = {
            Week(
                share_delivery.share.year, share_delivery.share.delivery_week
            ).monday(): share_delivery.delivery_station_day_id
            for share_delivery in ShareDelivery.objects.filter(
                subscription=subscription
            ).select_related("share")
        }
        assert station_day_by_monday == {
            **{_monday(n): ended.id for n in range(-6, -3)},
            **{_monday(n): successor.id for n in range(-3, 4)},
        }
        # Every past week resolved through the chain; none fell back to the
        # default station day.
        assert not [
            record for record in caplog.records if record.name == _SUBSCRIPTION_LOGGER
        ], caplog.text

    def test_flag_on_full_past_station_day_week_does_not_block_confirm(
        self, tenant, variation
    ):
        _set_tenant_settings(tenant, onboarding_mode=True)
        station_day = DeliveryStationDayFactory(capacity=1)
        occupier = _draft(
            variation, station_day, valid_from=_monday(-6), valid_until=_sunday(-1)
        )
        SubscriptionService().materialize_confirmed_subscription(
            occupier, earliest_monday=_BACKFILL_MONDAY
        )
        past_week = Week.withdate(_monday(-2))
        past_year_week = (past_week.year, past_week.week)
        slot = (station_day.id, *past_year_week)
        assert ShareDemandService.capacity_counts_by_week(
            station_day_ids=[station_day.id], year_weeks=[past_year_week]
        ) == {slot: 1}

        subscription = _draft(
            variation, station_day, valid_from=_monday(-10), valid_until=_sunday(3)
        )
        subscription.confirm(admin_user=JasminUserFactory(), save=True)

        assert _delivered_mondays(subscription) == [_monday(n) for n in range(-6, 4)]
        assert (
            ShareDemandService.capacity_counts_by_week(
                station_day_ids=[station_day.id], year_weeks=[past_year_week]
            )[slot]
            == 2
        )

    def test_flag_on_historically_full_variation_does_not_block_confirm(self, tenant):
        _set_tenant_settings(tenant, onboarding_mode=True)
        variation = ShareTypeVariationFactory(
            share_type=ShareTypeFactory(share_option="HARVEST_SHARE"), capacity=1
        )
        station_day = DeliveryStationDayFactory()
        SubscriptionFactory(
            member=MemberFactory(admin_confirmed=True),
            share_type_variation=variation,
            default_delivery_station_day=station_day,
            admin_confirmed=True,
            valid_from=_monday(-10),
            valid_until=_sunday(-1),
        )
        past_week = Week.withdate(_monday(-2))
        past_year_week = (past_week.year, past_week.week)
        assert VariationCapacityService.capacity_counts_by_week(
            variation_ids=[variation.id], year_weeks=[past_year_week]
        ) == {(variation.id, *past_year_week): 1}

        subscription = _draft(
            variation, station_day, valid_from=_monday(-10), valid_until=_sunday(3)
        )
        subscription.confirm(admin_user=JasminUserFactory(), save=True)

        assert _delivered_mondays(subscription) == [_monday(n) for n in range(-6, 4)]

    @pytest.mark.parametrize(
        ("onboarding_mode", "first_week"),
        [(False, 0), (True, -ONBOARDING_BACKFILL_WEEKS)],
    )
    def test_exact_billing_charges_every_materialised_delivery(
        self, tenant, variation, onboarding_mode, first_week
    ):
        _set_tenant_settings(tenant, onboarding_mode=onboarding_mode)
        subscription = _draft(
            variation,
            DeliveryStationDayFactory(),
            valid_from=_monday(-10),
            valid_until=_sunday(3),
        )
        subscription.confirm(admin_user=JasminUserFactory(), save=True)

        delivered = _delivered_mondays(subscription)
        assert delivered == [_monday(n) for n in range(first_week, 4)]
        planned = list(
            ChargeSchedule.objects.filter(
                subscription=subscription, status=ChargeStatus.PLANNED
            )
        )
        assert sum(
            (charge.expected_amount for charge in planned), Decimal("0.00")
        ) == Decimal("10.00") * len(delivered)
        charged_past_periods = [
            charge
            for charge in planned
            if charge.period_end < _CURRENT_MONDAY and charge.expected_amount > 0
        ]
        assert bool(charged_past_periods) is onboarding_mode
