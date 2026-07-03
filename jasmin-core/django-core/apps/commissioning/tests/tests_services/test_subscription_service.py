"""Tests for SubscriptionService."""

from __future__ import annotations

import datetime

import pytest
import time_machine

from apps.commissioning.errors import (
    CancellationAfterValidUntil,
    CancellationBeforeValidFrom,
    CancellationInPast,
    CancellationNotSunday,
    SubscriptionNotConfirmed,
)
from apps.commissioning.models import Share, ShareDelivery, Subscription
from apps.commissioning.services.subscription_service import SubscriptionService
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    JasminUserFactory,
    MemberFactory,
    PaymentCycleFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
)


# ---------------------------------------------------------------------------
# _get_delivery_weeks (pure — no DB needed)
# ---------------------------------------------------------------------------
class TestGetDeliveryWeeks:
    """SubscriptionService._get_delivery_weeks is a static helper."""

    def test_returns_weeks_in_range(self):
        # delivery_day=2 → Wednesday (iso weekday 3)
        start = datetime.date(2026, 4, 6)  # Monday
        end = datetime.date(2026, 4, 26)  # Sunday
        weeks = SubscriptionService._get_delivery_weeks(start, end, delivery_day=2)
        # Wednesdays in range: Apr 8, 15, 22
        assert len(weeks) == 3
        assert weeks[0] == (2026, 15)
        assert weeks[1] == (2026, 16)
        assert weeks[2] == (2026, 17)

    def test_empty_when_no_matching_day(self):
        # Only one day range with no Saturday
        start = datetime.date(2026, 4, 6)  # Monday
        end = datetime.date(2026, 4, 7)  # Tuesday
        weeks = SubscriptionService._get_delivery_weeks(start, end, delivery_day=5)
        assert weeks == []

    def test_single_week(self):
        # Range containing exactly one Wednesday
        start = datetime.date(2026, 4, 8)  # Wednesday
        end = datetime.date(2026, 4, 8)
        weeks = SubscriptionService._get_delivery_weeks(start, end, delivery_day=2)
        assert len(weeks) == 1
        assert weeks[0] == (2026, 15)

    def test_year_boundary(self):
        start = datetime.date(2025, 12, 29)  # Monday
        end = datetime.date(2026, 1, 11)  # Sunday
        # delivery_day=0 → Monday: Dec 29, Jan 5
        weeks = SubscriptionService._get_delivery_weeks(start, end, delivery_day=0)
        assert len(weeks) == 2


# ---------------------------------------------------------------------------
# create_subscription_with_related_objects
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateSubscriptionWithRelatedObjects:
    def test_creates_subscription_shares_and_deliveries(self, tenant):
        member = MemberFactory()
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
        payment_cycle = PaymentCycleFactory()

        validated_data = {
            "member": member.pk,
            "share_type_variation": variation.pk,
            "valid_from": datetime.date(2026, 4, 6),
            "valid_until": datetime.date(2026, 4, 26),
            "quantity": 1,
            "payment_cycle": payment_cycle,
            "default_delivery_station_day": station_day,
        }

        svc = SubscriptionService()
        sub = svc.create_bare_subscription(validated_data)
        sub.confirm(admin_user=JasminUserFactory(), save=True)

        assert isinstance(sub, Subscription)
        assert sub.pk is not None
        # Shares created for each delivery week (3 Wednesdays)
        shares = Share.objects.filter(share_type_variation=variation)
        assert shares.count() == 3
        # ShareDeliveries created for each share
        assert ShareDelivery.objects.filter(subscription=sub).count() == 3

    def test_independent_subscriptions_same_member_and_variation(self, tenant):
        # Subscriptions are independent: a member can hold two for the same
        # variation (e.g. consecutive terms) with no shared grouping object —
        # each carries member + share_type_variation directly.
        member = MemberFactory()
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
        payment_cycle = PaymentCycleFactory()

        base_data = {
            "member": member.pk,
            "share_type_variation": variation.pk,
            "valid_from": datetime.date(2026, 4, 6),
            "valid_until": datetime.date(2026, 4, 12),
            "quantity": 1,
            "payment_cycle": payment_cycle,
            "default_delivery_station_day": station_day,
        }

        svc = SubscriptionService()
        admin = JasminUserFactory()
        sub1 = svc.create_bare_subscription(dict(base_data))
        sub1.confirm(admin_user=admin, save=True)
        # Second subscription with later dates, same member + variation
        data2 = dict(base_data)
        data2["valid_from"] = datetime.date(2026, 5, 4)
        data2["valid_until"] = datetime.date(2026, 5, 10)
        sub2 = svc.create_bare_subscription(data2)
        sub2.confirm(admin_user=admin, save=True)

        # Two distinct, independent subscriptions — both carry the same member +
        # variation directly, with no shared grouping object.
        assert sub1.pk != sub2.pk
        assert sub1.member_id == sub2.member_id == member.pk
        assert (
            sub1.share_type_variation_id == sub2.share_type_variation_id == variation.pk
        )
        assert member.subscriptions.filter(share_type_variation=variation).count() == 2


# ---------------------------------------------------------------------------
# cancel_subscription — covers the front-of-house Cancel button flow
# wired in ``Abos.tsx`` via ``CancelSubscriptionModal`` →
# ``POST /api/commissioning/abos/{id}/cancel/``. The service is the
# single writer of the ``cancelled_*`` triplet; ``SubscriptionSerializer``
# locks them from PATCH (see test_subscription_serializer_locks.py).
#
# All these tests pin "today" to ``2026-03-30`` (a Monday) via
# ``time_machine`` so the next-Sunday floor is deterministic:
#   next_sunday(2026-03-30) == 2026-04-05 (Sunday)
# That puts the floor at the day BEFORE the subscription's valid_from
# (2026-04-06, Monday) — i.e. valid_from is binding, not the floor —
# so the existing test cases that target the valid_from / valid_until
# bounds still trip the right rule.
# ---------------------------------------------------------------------------


_FROZEN_TODAY = datetime.date(2026, 3, 30)  # Monday
_NEXT_SUNDAY = datetime.date(2026, 4, 5)  # ``today + 6 days``


@pytest.fixture
def confirmed_subscription(tenant):
    """A confirmed subscription with deliveries, ready to cancel.

    Dates picked so that:
      * ``valid_from`` is a Monday (model rule via TimeBoundMixin)
      * ``valid_until`` is a Sunday (same rule)
      * the term covers 3 Wednesdays so the delivery-deletion test has
        clean "before / after effective_at" expectations
    """
    member = MemberFactory()
    variation = ShareTypeVariationFactory()
    delivery_day = SharesDeliveryDayFactory(day_number=2)  # Wednesday
    station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
    payment_cycle = PaymentCycleFactory()

    validated_data = {
        "member": member.pk,
        "share_type_variation": variation.pk,
        "valid_from": datetime.date(2026, 4, 6),  # Monday
        "valid_until": datetime.date(2026, 4, 26),  # Sunday
        "quantity": 1,
        "payment_cycle": payment_cycle,
        "default_delivery_station_day": station_day,
    }
    svc = SubscriptionService()
    sub = svc.create_bare_subscription(validated_data)
    sub.confirm(admin_user=JasminUserFactory(), save=True)
    return sub


@pytest.mark.django_db
class TestCancelSubscription:
    """End-to-end coverage of ``SubscriptionService.cancel_subscription``.

    Pins all four validation rules (Sunday-only, next-Sunday floor,
    valid_from lower bound, valid_until upper bound) plus the happy-path
    side effects (cancellation triplet stamped, term truncated, future
    ShareDeliveries deleted). The PLANNED-charge drop / ISSUED-preserved
    behaviour is covered by the existing payments test suite.

    All tests run with ``today`` pinned to ``_FROZEN_TODAY`` (a Monday)
    so the next-Sunday floor is deterministic. Class-level
    ``@time_machine.travel`` only works on ``unittest.TestCase``
    subclasses; the pytest-style equivalent is the autouse fixture
    below.
    """

    @pytest.fixture(autouse=True)
    def _frozen_today(self):
        with time_machine.travel(_FROZEN_TODAY, tick=False):
            yield

    def test_happy_path_stamps_triplet_and_truncates_term(self, confirmed_subscription):
        actor = JasminUserFactory()
        # Sunday inside the term — Apr 12 is a Sunday.
        effective_at = datetime.date(2026, 4, 12)
        SubscriptionService().cancel_subscription(
            confirmed_subscription,
            cancelled_by=actor,
            effective_at=effective_at,
            reason="Member moved away.",
        )
        confirmed_subscription.refresh_from_db()
        assert confirmed_subscription.cancelled_at is not None
        assert confirmed_subscription.cancelled_by_id == actor.pk
        assert confirmed_subscription.cancelled_effective_at == effective_at
        # ``valid_until`` is truncated to ``effective_at``.
        assert confirmed_subscription.valid_until == effective_at
        # Reason was saved on the subscription.
        assert confirmed_subscription.cancellation_reason == "Member moved away."

    def test_re_cancel_is_a_noop_preserving_audit_stamp(self, confirmed_subscription):
        # MEM-4: a second cancel must NOT re-truncate the term, delete more
        # deliveries, or overwrite the original cancellation audit stamp.
        first_actor = JasminUserFactory()
        SubscriptionService().cancel_subscription(
            confirmed_subscription,
            cancelled_by=first_actor,
            effective_at=datetime.date(2026, 4, 12),  # Sunday
        )
        confirmed_subscription.refresh_from_db()
        original_cancelled_at = confirmed_subscription.cancelled_at
        original_valid_until = confirmed_subscription.valid_until
        remaining_after_first = ShareDelivery.objects.filter(
            subscription=confirmed_subscription
        ).count()

        # Second cancel: earlier effective date + a DIFFERENT actor → no-op.
        SubscriptionService().cancel_subscription(
            confirmed_subscription,
            cancelled_by=JasminUserFactory(),
            effective_at=datetime.date(2026, 4, 5),  # Sunday, earlier
        )
        confirmed_subscription.refresh_from_db()

        assert confirmed_subscription.cancelled_at == original_cancelled_at
        assert confirmed_subscription.cancelled_by_id == first_actor.pk
        assert confirmed_subscription.cancelled_effective_at == datetime.date(
            2026, 4, 12
        )
        assert confirmed_subscription.valid_until == original_valid_until
        assert (
            ShareDelivery.objects.filter(subscription=confirmed_subscription).count()
            == remaining_after_first
        )

    def test_future_share_deliveries_are_deleted(self, confirmed_subscription):
        # Sanity: 3 deliveries (Apr 8, 15, 22 — all Wednesdays in range).
        assert (
            ShareDelivery.objects.filter(subscription=confirmed_subscription).count()
            == 3
        )
        # Apr 12 is a Sunday. Apr 8 falls before; Apr 15 + Apr 22 after.
        SubscriptionService().cancel_subscription(
            confirmed_subscription,
            cancelled_by=JasminUserFactory(),
            effective_at=datetime.date(2026, 4, 12),
        )
        remaining = ShareDelivery.objects.filter(
            subscription=confirmed_subscription
        ).count()
        assert remaining == 1  # Only Apr 8 survives.

    def test_refuses_when_not_admin_confirmed(self, tenant):
        member = MemberFactory()
        variation = ShareTypeVariationFactory()
        station_day = DeliveryStationDayFactory()
        sub = SubscriptionService().create_bare_subscription(
            {
                "member": member.pk,
                "share_type_variation": variation.pk,
                "valid_from": datetime.date(2026, 4, 6),
                "valid_until": datetime.date(2026, 4, 26),
                "quantity": 1,
                "payment_cycle": PaymentCycleFactory(),
                "default_delivery_station_day": station_day,
            }
        )
        with pytest.raises(SubscriptionNotConfirmed) as exc:
            SubscriptionService().cancel_subscription(
                sub,
                cancelled_by=JasminUserFactory(),
                effective_at=datetime.date(2026, 4, 12),
            )
        assert exc.value.code == "subscription.cancel.not_confirmed"

    def test_refuses_non_sunday_effective_at(self, confirmed_subscription):
        # Apr 15 is a Wednesday — must be a Sunday.
        with pytest.raises(CancellationNotSunday) as exc:
            SubscriptionService().cancel_subscription(
                confirmed_subscription,
                cancelled_by=JasminUserFactory(),
                effective_at=datetime.date(2026, 4, 15),
            )
        assert exc.value.code == "subscription.cancel.not_sunday"

    def test_refuses_effective_at_before_next_sunday(self, confirmed_subscription):
        """Past Sundays are blocked — cancellation cannot rewind time.
        With ``today == 2026-03-30`` the next Sunday floor is Apr 5,
        so Mar 29 (a prior Sunday) must be refused."""
        with pytest.raises(CancellationInPast) as exc:
            SubscriptionService().cancel_subscription(
                confirmed_subscription,
                cancelled_by=JasminUserFactory(),
                effective_at=datetime.date(2026, 3, 29),  # Sunday in the past
            )
        assert exc.value.code == "subscription.cancel.in_past"

    def test_refuses_effective_at_before_valid_from(self, confirmed_subscription):
        """``valid_from`` floor — a Sunday before the term has begun is
        still refused (only relevant for future-dated subscriptions;
        here ``valid_from`` is Apr 6, the next-Sunday floor is Apr 5,
        so Mar 29 would fail the floor first → we pick a future
        confirmed_subscription via valid_from > floor)."""
        # The fixture's valid_from is 2026-04-06; next-Sunday floor is
        # 2026-04-05. Apr 5 sits BETWEEN floor and valid_from, so it
        # passes the floor but trips valid_from.
        with pytest.raises(CancellationBeforeValidFrom) as exc:
            SubscriptionService().cancel_subscription(
                confirmed_subscription,
                cancelled_by=JasminUserFactory(),
                effective_at=datetime.date(2026, 4, 5),
            )
        assert exc.value.code == "subscription.cancel.before_valid_from"

    def test_refuses_effective_at_after_valid_until(self, confirmed_subscription):
        """Sunday after the natural term end — refuse so the office
        can't accidentally EXTEND the term."""
        assert confirmed_subscription.valid_until is not None
        # May 3 is a Sunday after Apr 26.
        with pytest.raises(CancellationAfterValidUntil) as exc:
            SubscriptionService().cancel_subscription(
                confirmed_subscription,
                cancelled_by=JasminUserFactory(),
                effective_at=datetime.date(2026, 5, 3),
            )
        assert exc.value.code == "subscription.cancel.after_valid_until"

    def test_accepts_effective_at_equal_to_valid_until(self, confirmed_subscription):
        """Cancelling ON the term end (also a Sunday) is fine — same
        end date as the natural expiry, but stamps the audit triplet."""
        assert confirmed_subscription.valid_until is not None
        SubscriptionService().cancel_subscription(
            confirmed_subscription,
            cancelled_by=JasminUserFactory(),
            effective_at=confirmed_subscription.valid_until,
        )
        confirmed_subscription.refresh_from_db()
        assert confirmed_subscription.cancelled_at is not None

    def test_refuses_when_no_sunday_remains_in_term(self, tenant):
        """A term whose end is already in the past leaves no Sunday to
        cancel into. For any concrete ``effective_at`` the office could pass,
        the in-past floor fires first: the only Sundays on/before the term
        end (here Mar 22) are necessarily before the next-Sunday floor
        (Apr 5), so the request trips ``CancellationInPast``. (The dedicated
        ``NoSundayRemainsInTerm`` guard at the end of the method is a
        defensive backstop — checks 3+5 already imply ``next_sunday <=
        valid_until``, so it can't be reached for a specific date.)"""
        member = MemberFactory()
        variation = ShareTypeVariationFactory()
        station_day = DeliveryStationDayFactory()
        # Term ENDS before today. The next-Sunday floor (2026-04-05) is
        # already past 2026-03-22, so no Sunday remains.
        sub = SubscriptionService().create_bare_subscription(
            {
                "member": member.pk,
                "share_type_variation": variation.pk,
                "valid_from": datetime.date(2026, 3, 9),  # Monday
                "valid_until": datetime.date(2026, 3, 22),  # Sunday
                "quantity": 1,
                "payment_cycle": PaymentCycleFactory(),
                "default_delivery_station_day": station_day,
            }
        )
        sub.confirm(admin_user=JasminUserFactory(), save=True)
        # The only remaining valid Sunday (Mar 22) is before the next-Sunday
        # floor (Apr 5), so the in-past check fires.
        with pytest.raises(CancellationInPast) as exc:
            SubscriptionService().cancel_subscription(
                sub,
                cancelled_by=JasminUserFactory(),
                effective_at=datetime.date(2026, 3, 22),
            )
        assert exc.value.code == "subscription.cancel.in_past"
