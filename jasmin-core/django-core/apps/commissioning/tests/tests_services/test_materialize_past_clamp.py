"""Scope-A clamp: materialisation (and the capacity paths that share the week
list) never touch delivery weeks already in the PAST.

In normal use ``valid_from`` is a future Monday, so this is a no-op. It only
matters when a subscription with a HISTORICAL ``valid_from`` is confirmed — e.g.
an onboarding import of an existing member's subscription — where back-dated
ShareDeliveries (and their delivery-driven charges) must not be created.
"""

from __future__ import annotations

import datetime

import pytest
import time_machine
from isoweek import Week

from apps.commissioning.services.subscription_service import SubscriptionService
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    SubscriptionFactory,
)

_FROZEN = datetime.date(2026, 7, 20)  # a Monday
_CURRENT_MONDAY = Week.withdate(_FROZEN).monday()


def _weeks(subscription):
    return SubscriptionService._delivery_weeks_excluding_paused(subscription)


@pytest.mark.django_db
class TestMaterializePastClamp:
    @pytest.fixture(autouse=True)
    def _freeze(self):
        with time_machine.travel(_FROZEN, tick=False):
            yield

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
