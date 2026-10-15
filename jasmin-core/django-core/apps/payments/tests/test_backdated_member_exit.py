"""Where a member exit ends the member's subscriptions.

An exit dated today or later cancels a running subscription at the end of the
exit's week and force-ends one that hasn't started on the exit date itself.
``cancel_subscription`` refuses an end before the next Sunday, so an exit dated
in an earlier ISO week force-ends every subscription running past it. Each then
runs on to the end of the current week, never past ``valid_until``: the boxes
handed out since the exit stay delivered and billed, a charge a DRAFT run
bundles for them included, nothing after the current week is billed, and a
renewal that hasn't started gets nothing. Only the member and its coop shares
keep the backdated exit date.

"Today" is Wednesday 2026-07-08 (ISO week 28); the backdated exits fall two
weeks earlier. Every subscription delivers on Wednesdays at 10€ a box and is
billed monthly from its start, under both billing strategies.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
import time_machine
from django.utils import timezone

from apps.commissioning.models import CoopShare, Member, ShareDelivery, Subscription
from apps.commissioning.services.coop_share_service import CoopShareService
from apps.commissioning.services.member_cancellation import (
    _force_end_date,
    cancel_member_with_coop_shares,
)
from apps.commissioning.tests.factories import (
    CoopShareFactory,
    JasminUserFactory,
    MemberFactory,
    PaymentCycleFactory,
    ShareDeliveryFactory,
    ShareFactory,
    SubscriptionFactory,
)
from apps.commissioning.utils.iso_week_utils import share_delivery_date, weeks_in_range
from apps.payments.constants import BillingRunStatus, PaymentMethodOptions
from apps.payments.models import BillingRun, ChargeSchedule
from apps.payments.services import ChargeScheduleService
from apps.shared.tenants.models import TenantSettings

TODAY = datetime.date(2026, 7, 8)  # Wednesday, ISO week 28: a delivery day
# The Sunday ending today's week: the earliest end cancel_subscription accepts.
END_OF_THIS_WEEK = datetime.date(2026, 7, 12)
EXIT = datetime.date(2026, 6, 24)  # Wednesday, two weeks before today
TERM_START = datetime.date(2026, 1, 5)  # Monday, ISO week 2
TERM_END = datetime.date(2026, 12, 27)  # Sunday, ISO week 52
# The monthly period from 2026-06-05 holds the boxes of 06-10, 06-17, 06-24 and
# 07-01, all before today's.
JUNE_PERIOD = datetime.date(2026, 6, 5)


@pytest.fixture(autouse=True)
def _frozen_today():
    """Pin "today" to Wednesday 2026-07-08. Autouse, so it is in place before
    ``tenant_settings`` stamps its ``valid_from`` from the clock."""
    with time_machine.travel(
        datetime.datetime.combine(TODAY, datetime.time(12)), tick=False
    ):
        yield


@pytest.fixture(
    params=[
        TenantSettings.BILLING_STRATEGY_EXACT,
        TenantSettings.BILLING_STRATEGY_SMOOTHED,
    ],
    ids=["exact", "smoothed"],
)
def billing_strategy(request, tenant_settings) -> str:
    tenant_settings.billing_strategy = request.param
    tenant_settings.save()
    return request.param


def _member() -> Member:
    """A member admitted on ``TERM_START`` holding three coop shares paid that
    day. The shares are added while the member is pending, so the per-row
    bounds check doesn't apply."""
    member = MemberFactory(admin_confirmed=False, entry_date=TERM_START)
    CoopShareFactory(
        member=member,
        amount_of_coop_shares=3,
        admin_confirmed=True,
        paid_at=timezone.make_aware(
            datetime.datetime.combine(TERM_START, datetime.time(12))
        ),
    )
    Member.objects.filter(pk=member.pk).update(admin_confirmed=True)
    member.refresh_from_db()
    return member


def _subscription(member, valid_from, valid_until, **fields) -> Subscription:
    """A confirmed subscription with a box every Wednesday of its term and its
    charges planned."""
    subscription = SubscriptionFactory(
        member=member,
        valid_from=valid_from,
        valid_until=valid_until,
        quantity=1,
        price_per_delivery=Decimal("10.00"),
        payment_cycle=PaymentCycleFactory(choice="MONTHLY"),
        **fields,
    )
    Subscription.objects.filter(pk=subscription.pk).update(admin_confirmed=True)
    subscription.refresh_from_db()
    station_day = subscription.default_delivery_station_day
    for year, week in sorted(weeks_in_range(valid_from, valid_until)):
        ShareDeliveryFactory(
            share=ShareFactory(
                year=year,
                delivery_week=week,
                delivery_day=station_day.delivery_day,
                share_type_variation=subscription.share_type_variation,
            ),
            subscription=subscription,
            delivery_station_day=station_day,
        )
    ChargeScheduleService.regenerate_for_subscription(subscription)
    return subscription


def _renewal(current: Subscription, valid_until) -> Subscription:
    """The renewal of ``current``, starting the Monday after it ends."""
    return _subscription(
        current.member,
        current.valid_until + datetime.timedelta(days=1),
        valid_until,
        previous_subscription=current,
        share_type_variation=current.share_type_variation,
        default_delivery_station_day=current.default_delivery_station_day,
    )


def _bundle(subscription, period_start) -> ChargeSchedule:
    """Put the charge of the period from ``period_start`` into a DRAFT run, still
    PLANNED, as ``create_run`` leaves it until the export."""
    charge = ChargeSchedule.objects.get(
        subscription=subscription, period_start=period_start
    )
    charge.billing_run = BillingRun.objects.create(
        period_start=charge.period_start,
        period_end=charge.period_end,
        collection_date=charge.period_end + datetime.timedelta(days=5),
        payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
        status=BillingRunStatus.DRAFT,
        total_amount=charge.expected_amount,
        charge_count=1,
    )
    charge.save()
    return charge


def _delivery_dates(subscription) -> list[datetime.date]:
    return sorted(
        share_delivery_date(share_delivery)
        for share_delivery in ShareDelivery.objects.filter(
            subscription=subscription
        ).select_related("share__delivery_day")
    )


def _plan(subscription) -> list[tuple]:
    """Each charge's period, amount and run, in period order."""
    return list(
        ChargeSchedule.objects.filter(subscription=subscription)
        .order_by("period_start")
        .values_list("period_start", "period_end", "expected_amount", "billing_run_id")
    )


def _billed(subscription) -> Decimal:
    return sum(
        ChargeSchedule.objects.filter(subscription=subscription).values_list(
            "expected_amount", flat=True
        ),
        Decimal("0.00"),
    )


def _billed_after(subscription, day) -> list[ChargeSchedule]:
    """The charges with an amount to collect for a period starting after ``day``."""
    return list(
        ChargeSchedule.objects.filter(
            subscription=subscription,
            period_start__gt=day,
            expected_amount__gt=Decimal("0.00"),
        )
    )


def _exit(member, exit_date, *, force=True):
    return cancel_member_with_coop_shares(
        member,
        cancelled_effective_at=exit_date,
        cancelled_by=JasminUserFactory(),
        force=force,
    )


class TestForceEndDate:
    """Where the member exit ends a subscription it force-ends."""

    @pytest.mark.parametrize(
        ("exit_date", "valid_until", "end"),
        [
            # An exit today or later ends it on the exit date itself...
            (TODAY, TERM_END, TODAY),
            (datetime.date(2026, 7, 21), TERM_END, datetime.date(2026, 7, 21)),
            # ...an earlier one at the end of this week, whichever week it lies in...
            (datetime.date(2026, 7, 6), TERM_END, END_OF_THIS_WEEK),
            (EXIT, TERM_END, END_OF_THIS_WEEK),
            # ...or at the end of a term that ends first.
            (EXIT, datetime.date(2026, 7, 5), datetime.date(2026, 7, 5)),
        ],
        ids=["today", "later", "earlier-this-week", "backdated", "term-ended"],
    )
    def test_the_end(self, exit_date, valid_until, end):
        subscription = Subscription(valid_until=valid_until)

        assert _force_end_date(subscription, exit_date=exit_date, today=TODAY) == end


@pytest.mark.django_db
class TestBackdatedMemberExit:
    def test_the_weeks_since_the_exit_stay_delivered_and_billed(
        self, tenant, billing_strategy
    ):
        member = _member()
        subscription = _subscription(member, TERM_START, TERM_END)
        bundled = _bundle(subscription, JUNE_PERIOD)

        result = _exit(member, EXIT)

        assert result.subscriptions_ended == [subscription.id]
        subscription.refresh_from_db()
        assert subscription.cancelled_at is not None
        assert subscription.cancelled_effective_at == END_OF_THIS_WEEK
        assert subscription.valid_until == TERM_END
        # The 27 Wednesdays from 2026-01-07 up to today stay delivered.
        delivery_dates = _delivery_dates(subscription)
        assert len(delivery_dates) == 27
        assert delivery_dates[-1] == TODAY
        # The charge in the DRAFT run keeps its run and its amount...
        kept = ChargeSchedule.objects.get(pk=bundled.pk)
        assert kept.billing_run_id == bundled.billing_run_id
        assert kept.expected_amount == bundled.expected_amount
        # ...the period holding today ends with the week...
        this_period = ChargeSchedule.objects.get(
            subscription=subscription, period_start=datetime.date(2026, 7, 5)
        )
        assert this_period.period_end == END_OF_THIS_WEEK
        assert this_period.expected_amount > Decimal("0.00")
        # ...every box delivered is billed, and nothing after the week.
        assert _billed(subscription) == Decimal("270.00")
        assert _billed_after(subscription, END_OF_THIS_WEEK) == []

    def test_the_member_and_its_coop_shares_keep_the_backdated_exit_date(
        self, tenant, tenant_settings
    ):
        member = _member()
        _subscription(member, datetime.date(2026, 6, 1), datetime.date(2026, 8, 30))

        _exit(member, EXIT)

        member.refresh_from_db()
        assert member.cancelled_effective_at == EXIT
        share = CoopShare.objects.get(member=member)
        assert share.cancelled_effective_at == EXIT

    def test_a_renewal_that_has_not_started_is_cancelled_with_nothing_billed(
        self, tenant, billing_strategy
    ):
        member = _member()
        current = _subscription(member, TERM_START, datetime.date(2026, 8, 2))
        renewal = _renewal(current, TERM_END)
        bundled = _bundle(renewal, renewal.valid_from)

        result = _exit(member, EXIT)

        assert set(result.subscriptions_ended) == {current.id, renewal.id}
        renewal.refresh_from_db()
        assert renewal.cancelled_at is not None
        # It ends before it starts, so it runs no day at all.
        assert renewal.cancelled_effective_at == END_OF_THIS_WEEK
        assert renewal.cancelled_effective_at < renewal.valid_from
        assert _delivery_dates(renewal) == []
        assert not ChargeSchedule.objects.filter(
            billing_run_id=bundled.billing_run_id
        ).exists()
        assert _billed(renewal) == Decimal("0.00")
        # The subscription it renews bills its boxes up to today's.
        assert _delivery_dates(current)[-1] == TODAY
        assert _billed(current) == Decimal("270.00")

    def test_a_subscription_that_ended_before_this_week_is_left_as_it_ran(
        self, tenant, billing_strategy
    ):
        member = _member()
        # Its last week is the one after the exit's, before today's.
        ended = _subscription(member, TERM_START, datetime.date(2026, 7, 5))
        _bundle(ended, JUNE_PERIOD)
        ChargeScheduleService.regenerate_for_subscription(ended)
        delivery_dates, plan = _delivery_dates(ended), _plan(ended)

        # Nothing active is left, so the exit needs no force.
        result = _exit(member, EXIT, force=False)

        assert result.subscriptions_ended == [ended.id]
        ended.refresh_from_db()
        assert ended.cancelled_at is not None
        assert ended.cancelled_effective_at == ended.valid_until
        assert _delivery_dates(ended) == delivery_dates
        assert _plan(ended) == plan

    def test_a_backdated_coop_share_transfer_leaves_an_ended_subscription_as_it_ran(
        self, tenant, billing_strategy
    ):
        giver = _member()
        receiver = _member()
        ended = _subscription(giver, TERM_START, datetime.date(2026, 7, 5))
        _bundle(ended, JUNE_PERIOD)
        ChargeScheduleService.regenerate_for_subscription(ended)
        delivery_dates, plan = _delivery_dates(ended), _plan(ended)

        # Giving every share ends the membership on the transfer date.
        result = CoopShareService.transfer(
            from_member=giver,
            to_member=receiver,
            amount=3,
            transfer_date=EXIT,
            actor=JasminUserFactory(),
            confirm_member_cancellation=True,
        )

        assert result.from_member_cancelled is True
        giver.refresh_from_db()
        assert giver.cancelled_effective_at == EXIT
        ended.refresh_from_db()
        assert ended.cancelled_at is not None
        assert ended.cancelled_effective_at == ended.valid_until
        assert _delivery_dates(ended) == delivery_dates
        assert _plan(ended) == plan


@pytest.mark.django_db
class TestForwardDatedMemberExit:
    """An exit dated today or later is untouched by the backdated-exit rule: the
    running subscription is cancelled at the end of the exit's week and a renewal
    that hasn't started is force-ended on the exit date itself."""

    @pytest.mark.parametrize(
        ("exit_date", "end_of_exit_week", "last_box"),
        [
            (TODAY, END_OF_THIS_WEEK, TODAY),
            (
                datetime.date(2026, 7, 21),
                datetime.date(2026, 7, 26),
                datetime.date(2026, 7, 22),
            ),
        ],
        ids=["today", "a-later-week"],
    )
    def test_the_subscriptions_end_with_the_exit(
        self, tenant, billing_strategy, exit_date, end_of_exit_week, last_box
    ):
        member = _member()
        current = _subscription(member, TERM_START, datetime.date(2026, 8, 2))
        renewal = _renewal(current, TERM_END)

        _exit(member, exit_date)

        member.refresh_from_db()
        assert member.cancelled_effective_at == exit_date
        current.refresh_from_db()
        assert current.valid_until == end_of_exit_week
        assert current.cancelled_effective_at == end_of_exit_week
        delivery_dates = _delivery_dates(current)
        assert delivery_dates[-1] == last_box
        assert _billed(current) == Decimal("10.00") * len(delivery_dates)
        assert _billed_after(current, end_of_exit_week) == []
        renewal.refresh_from_db()
        assert renewal.cancelled_effective_at == exit_date
        assert _delivery_dates(renewal) == []
        assert _billed(renewal) == Decimal("0.00")
