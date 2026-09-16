"""Onboarding mode and confirming a subscription of a member who has left.

``subscriptions/{id}/confirm`` refuses a member with ``cancelled_at`` set
(``member.already_cancelled``). While ``TenantSettings.onboarding_mode`` is on,
the office records subscriptions that already ran, so the confirm goes through
when the member is already confirmed and the subscription ends by the exit date;
deliveries and charges then stop at the term end.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
import time_machine
from django.urls import reverse
from django.utils import timezone
from isoweek import Week
from rest_framework import status

from apps.commissioning.models import Member, ShareDelivery, Subscription
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    MemberFactory,
    PaymentCycleFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)
from apps.payments.constants import ChargeStatus
from apps.payments.models import ChargeSchedule
from apps.shared.tenants.models import TenantSettings

# Frozen on Monday 2026-07-20, so onboarding backfills from Monday 2026-06-08.
TERM_START = datetime.date(2026, 1, 5)
EXIT_DATE = datetime.date(2026, 6, 30)
TERM_END_BY_EXIT = datetime.date(2026, 6, 28)  # the Sunday before the exit
TERM_END_AFTER_EXIT = datetime.date(2026, 7, 5)
BACKFILLED_MONDAYS = [
    datetime.date(2026, 6, 8),
    datetime.date(2026, 6, 15),
    datetime.date(2026, 6, 22),
]


@pytest.fixture(autouse=True)
def _frozen_clock():
    # A Monday away from any year boundary.
    with time_machine.travel(datetime.datetime(2026, 7, 20, 12, 0), tick=False):
        yield


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


@pytest.fixture()
def onboarding_mode(tenant):
    _set_tenant_settings(tenant, onboarding_mode=True)


@pytest.fixture()
def onboarding_mode_off(tenant):
    _set_tenant_settings(tenant, onboarding_mode=False)


@pytest.fixture()
def variation(tenant):
    return ShareTypeVariationFactory(
        share_type=ShareTypeFactory(share_option="HARVEST_SHARE")
    )


def _departed_member_draft(
    variation, *, valid_until: datetime.date, member_confirmed: bool = True
) -> Subscription:
    """An unconfirmed subscription, 10.00 per delivery and billed monthly, of a
    member who left on ``EXIT_DATE``. The exit is recorded after the
    subscription was entered."""
    member = MemberFactory(
        admin_confirmed=member_confirmed,
        entry_date=datetime.date(2020, 3, 2) if member_confirmed else None,
    )
    subscription = SubscriptionFactory(
        member=member,
        share_type_variation=variation,
        default_delivery_station_day=DeliveryStationDayFactory(),
        valid_from=TERM_START,
        valid_until=valid_until,
        quantity=1,
        price_per_delivery=Decimal("10.00"),
        payment_cycle=PaymentCycleFactory(choice="MONTHLY"),
    )
    Member.objects.filter(pk=member.pk).update(
        cancelled_at=timezone.make_aware(datetime.datetime(2026, 7, 1, 9, 0)),
        cancelled_effective_at=EXIT_DATE,
    )
    return subscription


def _confirm_url(subscription: Subscription) -> str:
    return reverse("abos-confirm", kwargs={"pk": subscription.pk})


def _delivered_mondays(subscription: Subscription) -> list[datetime.date]:
    return sorted(
        Week(share_delivery.share.year, share_delivery.share.delivery_week).monday()
        for share_delivery in ShareDelivery.objects.filter(
            subscription=subscription
        ).select_related("share")
    )


@pytest.mark.django_db
class TestDepartedMemberSubscriptionConfirmFlagOff:
    def test_is_refused(self, api_client, onboarding_mode_off, variation):
        subscription = _departed_member_draft(variation, valid_until=TERM_END_BY_EXIT)

        resp = api_client.post(_confirm_url(subscription))

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == "member.already_cancelled"
        subscription.refresh_from_db()
        assert not subscription.admin_confirmed
        assert _delivered_mondays(subscription) == []


@pytest.mark.django_db
class TestDepartedMemberSubscriptionConfirmFlagOn:
    def test_subscription_ending_by_the_exit_is_confirmed_and_backfilled(
        self, api_client, onboarding_mode, variation
    ):
        subscription = _departed_member_draft(variation, valid_until=TERM_END_BY_EXIT)

        resp = api_client.post(_confirm_url(subscription))

        assert resp.status_code == status.HTTP_200_OK, resp.data
        subscription.refresh_from_db()
        assert subscription.admin_confirmed
        assert _delivered_mondays(subscription) == BACKFILLED_MONDAYS
        planned = list(
            ChargeSchedule.objects.filter(
                subscription=subscription, status=ChargeStatus.PLANNED
            )
        )
        assert sum(
            (charge.expected_amount for charge in planned), Decimal("0.00")
        ) == Decimal("30.00")
        assert all(charge.period_start <= EXIT_DATE for charge in planned)
        member = Member.objects.get(pk=subscription.member_id)
        assert member.admin_confirmed
        assert member.cancelled_effective_at == EXIT_DATE

    def test_draft_wound_down_by_the_member_exit_is_confirmed(
        self, api_client, onboarding_mode, variation
    ):
        subscription = _departed_member_draft(variation, valid_until=TERM_END_BY_EXIT)
        # The member exit stamps a draft cancelled at its term end.
        Subscription.objects.filter(pk=subscription.pk).update(
            cancelled_at=timezone.make_aware(datetime.datetime(2026, 7, 1, 9, 0)),
            cancelled_effective_at=TERM_END_BY_EXIT,
        )

        resp = api_client.post(_confirm_url(subscription))

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert _delivered_mondays(subscription) == BACKFILLED_MONDAYS

    def test_subscription_ending_after_the_exit_is_refused(
        self, api_client, onboarding_mode, variation
    ):
        subscription = _departed_member_draft(
            variation, valid_until=TERM_END_AFTER_EXIT
        )

        resp = api_client.post(_confirm_url(subscription))

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == "subscription.ends_after_member_exit"
        assert resp.data["details"] == {"exit_date": EXIT_DATE.isoformat()}
        subscription.refresh_from_db()
        assert not subscription.admin_confirmed
        assert _delivered_mondays(subscription) == []
        assert not ChargeSchedule.objects.filter(subscription=subscription).exists()

    def test_unconfirmed_departed_member_is_refused(
        self, api_client, onboarding_mode, variation
    ):
        subscription = _departed_member_draft(
            variation, valid_until=TERM_END_BY_EXIT, member_confirmed=False
        )

        resp = api_client.post(_confirm_url(subscription))

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == "subscription.member_not_admitted"
        subscription.refresh_from_db()
        assert not subscription.admin_confirmed
        member = Member.objects.get(pk=subscription.member_id)
        assert not member.admin_confirmed
        assert member.entry_date is None
