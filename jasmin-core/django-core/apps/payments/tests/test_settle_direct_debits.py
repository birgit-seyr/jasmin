"""The ``settle_collected_direct_debits`` Huey periodic task.

An exported direct-debit run is settled once a member can no longer have the
debit refunded: its issued charges become PAID, which ends them blocking the
member's erasure. Runs still inside the window, bank-transfer runs and draft
runs are left as they are.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from unittest import mock

import pytest
import time_machine

from apps.gdpr.services import GDPRService
from apps.payments.constants import (
    DIRECT_DEBIT_SETTLES_AFTER,
    BillingRunStatus,
    ChargeStatus,
    PaymentMethodOptions,
)
from apps.payments.errors import BillingRunChargesBeingReplanned
from apps.payments.models import BillingRun, ChargeSchedule
from apps.payments.services import BillingRunService
from apps.payments.tasks import settle_collected_direct_debits

TODAY = datetime.date(2026, 5, 11)
# The latest collection date a run settles on today.
LAST_SETTLED = TODAY - DIRECT_DEBIT_SETTLES_AFTER


@pytest.fixture(autouse=True)
def _frozen_today():
    with time_machine.travel(datetime.datetime(2026, 5, 11, 12, 0), tick=False):
        yield


def _run(member, subscription, *, charge_status=ChargeStatus.ISSUED, **run_fields):
    """An exported direct-debit run collected on ``LAST_SETTLED``, with one
    issued charge; ``run_fields`` override the run's."""
    period_start = datetime.date(2026, 2, 2)
    run = BillingRun.objects.create(
        **{
            "period_start": period_start,
            "period_end": period_start + datetime.timedelta(days=27),
            "collection_date": LAST_SETTLED,
            "payment_method": PaymentMethodOptions.SEPA_DIRECT_DEBIT,
            "status": BillingRunStatus.EXPORTED,
            "total_amount": Decimal("25.00"),
            "charge_count": 1,
            **run_fields,
        }
    )
    charge = ChargeSchedule.objects.create(
        member=member,
        subscription=subscription,
        period_start=period_start,
        period_end=period_start + datetime.timedelta(days=27),
        due_date=period_start,
        expected_amount=Decimal("25.00"),
        status=charge_status,
        billing_run=run,
    )
    return run, charge


def _statuses(run, charge):
    run.refresh_from_db()
    charge.refresh_from_db()
    return run.status, charge.status


@pytest.mark.django_db
class TestSettleCollectedDirectDebits:
    def test_a_run_past_the_refund_window_is_settled(
        self, tenant, billing_profile, subscription, member
    ):
        run, charge = _run(member, subscription)

        result = settle_collected_direct_debits.call_local()

        assert _statuses(run, charge) == (
            BillingRunStatus.SETTLED,
            ChargeStatus.PAID,
        )
        assert result["runs_settled"] >= 1
        assert result["charges_paid"] >= 1
        assert result["tenants_failed"] == 0

    def test_a_run_inside_the_refund_window_stays_exported(
        self, tenant, billing_profile, subscription, member
    ):
        run, charge = _run(
            member,
            subscription,
            collection_date=LAST_SETTLED + datetime.timedelta(days=1),
        )

        settle_collected_direct_debits.call_local()

        assert _statuses(run, charge) == (
            BillingRunStatus.EXPORTED,
            ChargeStatus.ISSUED,
        )

    def test_a_bank_transfer_run_stays_exported(self, tenant, subscription, member):
        run, charge = _run(
            member,
            subscription,
            payment_method=PaymentMethodOptions.BANK_TRANSFER,
        )

        settle_collected_direct_debits.call_local()

        assert _statuses(run, charge) == (
            BillingRunStatus.EXPORTED,
            ChargeStatus.ISSUED,
        )

    def test_a_draft_run_is_left_alone(
        self, tenant, billing_profile, subscription, member
    ):
        run, charge = _run(
            member,
            subscription,
            status=BillingRunStatus.DRAFT,
            charge_status=ChargeStatus.PLANNED,
        )

        settle_collected_direct_debits.call_local()

        assert _statuses(run, charge) == (
            BillingRunStatus.DRAFT,
            ChargeStatus.PLANNED,
        )

    def test_only_an_issued_charge_becomes_paid(
        self, tenant, billing_profile, subscription, member
    ):
        run, issued = _run(member, subscription)
        waived = ChargeSchedule.objects.create(
            member=member,
            subscription=subscription,
            period_start=datetime.date(2026, 3, 2),
            period_end=datetime.date(2026, 3, 29),
            due_date=datetime.date(2026, 3, 2),
            expected_amount=Decimal("25.00"),
            status=ChargeStatus.WAIVED,
            billing_run=run,
        )

        settle_collected_direct_debits.call_local()

        waived.refresh_from_db()
        assert _statuses(run, issued) == (
            BillingRunStatus.SETTLED,
            ChargeStatus.PAID,
        )
        assert waived.status == ChargeStatus.WAIVED

    def test_a_run_a_replan_holds_is_settled_the_next_day(
        self, tenant, billing_profile, subscription, member
    ):
        run, charge = _run(member, subscription)

        with mock.patch.object(
            BillingRunService,
            "lock_charges",
            side_effect=BillingRunChargesBeingReplanned("held"),
        ):
            result = settle_collected_direct_debits.call_local()

        assert _statuses(run, charge) == (
            BillingRunStatus.EXPORTED,
            ChargeStatus.ISSUED,
        )
        assert result["tenants_failed"] == 0

        settle_collected_direct_debits.call_local()

        assert _statuses(run, charge) == (
            BillingRunStatus.SETTLED,
            ChargeStatus.PAID,
        )

    def test_a_settled_charge_no_longer_blocks_the_members_erasure(
        self, tenant, billing_profile, subscription, member
    ):
        _run(member, subscription)
        assert any(
            "open charge(s)" in reason
            for reason in GDPRService.check_retention_blocks(member.user)
        )

        settle_collected_direct_debits.call_local()

        assert not any(
            "open charge(s)" in reason
            for reason in GDPRService.check_retention_blocks(member.user)
        )
