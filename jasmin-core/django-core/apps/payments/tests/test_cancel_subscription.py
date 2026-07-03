"""Regression tests for ``SubscriptionService.cancel_subscription`` —
the rule that locked ChargeSchedule rows (ISSUED/PAID/FAILED/WAIVED)
must NEVER be touched, while PLANNED rows past the new end-date go away.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
import time_machine

from apps.commissioning.services.subscription_service import SubscriptionService
from apps.payments.constants import ChargeStatus
from apps.payments.models import ChargeSchedule
from apps.payments.services import ChargeScheduleService


def _make_charge(member, subscription, *, due_date, status=ChargeStatus.PLANNED):
    c = ChargeSchedule.objects.create(
        member=member,
        subscription=subscription,
        period_start=due_date,
        period_end=due_date + datetime.timedelta(days=27),
        due_date=due_date,
        expected_amount=Decimal("10"),
        currency="EUR",
        description=f"charge {due_date.isoformat()}",
        status=ChargeStatus.PLANNED,
    )
    if status != ChargeStatus.PLANNED:
        c.status = status
        c.save(allow_immutable_change=True)
    return c


@pytest.mark.django_db
class TestCancelSubscriptionPreservesLockedCharges:
    # Freeze "today" before the hardcoded 2026-06-28 Sunday effective date so
    # the cancel_subscription next-Sunday guard stays satisfied regardless of
    # the real wall-clock date (these dates are otherwise time-fragile).
    @time_machine.travel("2026-06-01")
    def test_planned_after_effective_date_deleted(
        self,
        tenant,
        tenant_settings,
        billing_profile,
        member,
        subscription,
        user,
    ):
        # Confirm the subscription so cancel is allowed.
        subscription.admin_confirmed = True
        subscription.save()

        keep = _make_charge(member, subscription, due_date=datetime.date(2026, 2, 1))
        drop = _make_charge(member, subscription, due_date=datetime.date(2026, 8, 1))

        # ``valid_until`` must land on a Sunday (TimeBoundMixin week boundary).
        SubscriptionService().cancel_subscription(
            subscription,
            cancelled_by=user,
            effective_at=datetime.date(2026, 6, 28),
        )

        # The future PLANNED row must be gone (either via direct delete or
        # via the schedule regen that runs at the end of cancel).
        assert not ChargeSchedule.objects.filter(pk=drop.pk).exists()
        # No PLANNED charge may remain for a period strictly after the
        # cancellation date — that's the security invariant.
        assert not ChargeSchedule.objects.filter(
            subscription=subscription,
            status=ChargeStatus.PLANNED,
            due_date__gt=datetime.date(2026, 6, 28),
        ).exists()
        # ``keep`` was a hand-inserted PLANNED row; regenerate_for_subscription
        # wipes all PLANNED rows and rebuilds from the schedule, so we don't
        # assert on its survival here — just on the post-condition above.
        del keep

    @time_machine.travel("2026-06-01")
    def test_locked_after_effective_date_preserved(
        self,
        tenant,
        tenant_settings,
        billing_profile,
        member,
        subscription,
        user,
    ):
        subscription.admin_confirmed = True
        subscription.save()

        # An already-issued charge in the future (e.g. SEPA mandate already
        # collected). Cancellation must not delete or refund it from here —
        # that's a separate financial operation.
        locked = _make_charge(
            member,
            subscription,
            due_date=datetime.date(2026, 8, 1),
            status=ChargeStatus.ISSUED,
        )

        SubscriptionService().cancel_subscription(
            subscription,
            cancelled_by=user,
            effective_at=datetime.date(2026, 6, 28),
        )

        locked.refresh_from_db()
        assert locked.status == ChargeStatus.ISSUED


@pytest.mark.django_db
class TestRegenerateForSubscriptionIdempotent:
    def test_running_twice_yields_same_state(
        self,
        tenant,
        tenant_settings,
        billing_profile,
        member,
        subscription,
    ):
        ChargeScheduleService.regenerate_for_subscription(subscription)
        first = sorted(
            ChargeSchedule.objects.filter(subscription=subscription).values_list(
                "due_date", "expected_amount"
            )
        )

        ChargeScheduleService.regenerate_for_subscription(subscription)
        second = sorted(
            ChargeSchedule.objects.filter(subscription=subscription).values_list(
                "due_date", "expected_amount"
            )
        )

        assert first == second
