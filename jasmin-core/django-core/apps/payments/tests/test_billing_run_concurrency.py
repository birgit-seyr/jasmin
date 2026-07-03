"""Concurrency test for ``BillingRunService.create_run`` — no double-bundling.

``create_run`` selects eligible PLANNED charges (``billing_run__isnull=True``)
and assigns each to a new ``BillingRun`` inside ``@transaction.atomic``. Under
Postgres READ COMMITTED, two concurrent runs over an overlapping period could
both read the same unassigned charges and bundle them into two different runs
— double-charging a member's SEPA mandate (the second writer silently
overwrites the first run's FK pointer while the first run's ``charge_count`` /
total still counted them).

The fix is ``select_for_update(skip_locked=True, of=("self",))`` on the
eligible queryset: the loser skips already-locked charges and bundles only
what's left. This test proves it with real threads (a mocked query wouldn't
reproduce the interleaving), mirroring the invoice/member numbering
concurrency tests.

``@pytest.mark.django_db(transaction=True)`` is required: worker threads open
their own connections and can only see COMMITTED rows, and the row locks only
block across committed transactions.
"""

from __future__ import annotations

import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal

import pytest
from django.db import connection, connections
from django.utils import timezone

from apps.commissioning.tests.factories import (
    PaymentCycleFactory,
    SubscriptionFactory,
)
from apps.payments.constants import BillingRunStatus, ChargeStatus
from apps.payments.models import BillingRun, ChargeSchedule
from apps.payments.services import BillingRunService


@pytest.fixture()
def subscription(tenant, member):
    """A minimal subscription that creates NO ``SharesDeliveryDay``.

    Overrides the shared payments ``subscription`` fixture. That one sets
    ``default_delivery_station_day`` via a factory, which transitively
    creates a ``SharesDeliveryDay`` with ``day_number=2``. That model's
    overlap guard is keyed on ``day_number`` ALONE (a global scope, not
    per-member) — so under ``transaction=True`` the first test commits the
    row and the next test's identical ``day_number=2`` row trips
    "Overlapping period detected". ``default_delivery_station_day`` is
    nullable and ``create_run`` never reads it, so we drop it entirely and
    sidestep the cross-test collision. Member + share-type variation are
    freshly created per test, so the remaining chain can't collide.
    """
    return SubscriptionFactory(
        member=member,
        valid_from=datetime.date(2026, 1, 5),
        valid_until=datetime.date(2026, 12, 27),
        quantity=1,
        price_per_delivery=Decimal("10.00"),
        payment_cycle=PaymentCycleFactory(choice="MONTHLY"),
        default_delivery_station_day=None,
    )


def _make_planned_charge(member, subscription, *, due_date, amount=Decimal("25.00")):
    return ChargeSchedule.objects.create(
        member=member,
        subscription=subscription,
        period_start=due_date,
        period_end=due_date + datetime.timedelta(days=27),
        due_date=due_date,
        expected_amount=amount,
        currency="EUR",
        description="Subscription charge",
        status=ChargeStatus.PLANNED,
    )


def _create_run_in_thread(schema_name, period_start, period_end, collection_date):
    """Worker: fresh connection in the tenant schema, call create_run.

    Returns ``(run_pk, charge_count)`` for the run it created, or
    ``(None, 0)`` when it found nothing to bundle (another thread had already
    locked/claimed the charges — a legitimate outcome with skip_locked, NOT
    an error). Closes thread-local connections in a finally so pytest-django's
    post-test flush isn't blocked by a lingering lock-holding connection.
    """
    from django_tenants.utils import schema_context

    from apps.payments.errors import NoEligibleCharges, NoValidSepaMandates

    connection.close()
    try:
        with schema_context(schema_name):
            try:
                run = BillingRunService.create_run(
                    period_start=period_start,
                    period_end=period_end,
                    collection_date=collection_date,
                )
                return (run.pk, run.charge_count)
            except (NoEligibleCharges, NoValidSepaMandates):
                return (None, 0)
    finally:
        for conn in connections.all():
            conn.close()


def _export_in_thread(tenant, run_pk):
    """Worker: fresh connection in the tenant schema, call ``export``.

    Uses ``tenant_context(tenant)`` (not ``schema_context(name)``): the SEPA
    XML builder reads ``connection.tenant.sepa_creditor_*``, which a
    schema-only FakeTenant lacks. Returns ``"exported"`` for the thread that
    produced the file, or ``"not_draft"`` for the one that lost the race (the
    run was already EXPORTED by the time it acquired the row lock). Closes
    thread-local connections in a finally so the post-test flush isn't blocked.
    """
    from django_tenants.utils import tenant_context

    from apps.payments.errors import BillingRunNotDraft

    connection.close()
    try:
        with tenant_context(tenant):
            try:
                run = BillingRun.objects.get(pk=run_pk)
                BillingRunService.export(run)
                return "exported"
            except BillingRunNotDraft:
                return "not_draft"
    finally:
        for conn in connections.all():
            conn.close()


@pytest.mark.django_db(transaction=True)
class TestBillingRunExportConcurrency:
    """``export`` must serialise on the BillingRun row so two concurrent
    exports of the same DRAFT run can't both emit a valid pain.008 (the
    member would be direct-debited twice if both files reach the bank)."""

    @pytest.fixture(autouse=True)
    def _hermetic_charge_tables(self, tenant):
        ChargeSchedule.objects.all().delete()
        BillingRun.objects.all().delete()

    def test_concurrent_export_emits_one_file_one_conflict(
        self, tenant, member, subscription, billing_profile
    ):
        # The export reads ``tenant.sepa_creditor_*`` off the IN-MEMORY tenant
        # (``tenant_context(tenant)`` in the worker). Set them directly instead
        # of via the shared ``tenant_settings`` fixture: that fixture also
        # INSERTs a public ``TenantSettings`` row, and under ``transaction=True``
        # a prior test's flush can truncate the session tenant's public
        # ``tenants_tenant`` row, making that FK insert fail. ``create_run`` /
        # ``export`` don't need a persisted TenantSettings — ``_billing_config``
        # safely falls back to EXACT when none exists.
        tenant.iban = "DE89370400440532013000"
        tenant.sepa_creditor_id = "DE98ZZZ09999999999"
        tenant.sepa_creditor_name = "Test Farm e.G."
        tenant.sepa_creditor_bic = "COBADEFFXXX"

        _make_planned_charge(member, subscription, due_date=datetime.date(2026, 2, 5))
        run = BillingRunService.create_run(
            period_start=datetime.date(2026, 2, 1),
            period_end=datetime.date(2026, 2, 28),
            collection_date=timezone.localdate() + datetime.timedelta(days=30),
        )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_export_in_thread, tenant, run.pk) for _ in range(2)]
            results = sorted(f.result() for f in as_completed(futures))

        # Exactly one export produced the file; the other hit the locked
        # re-check and raised BillingRunNotDraft instead of a 2nd pain.008.
        assert results == ["exported", "not_draft"]
        run.refresh_from_db()
        assert run.status == BillingRunStatus.EXPORTED
        assert run.sepa_xml_export  # one file attached, not overwritten by a 2nd


@pytest.mark.django_db(transaction=True)
class TestBillingRunConcurrency:
    # test_pytest schema is shared + committed across these transaction=True
    # tests, so wipe charges/runs first (otherwise stale rows break the counts).
    @pytest.fixture(autouse=True)
    def _hermetic_charge_tables(self, tenant):
        ChargeSchedule.objects.all().delete()
        BillingRun.objects.all().delete()

    def test_no_double_bundling_under_concurrent_create_run(
        self, tenant, member, subscription, billing_profile
    ):
        n_charges = 20
        period_start = datetime.date(2026, 2, 1)
        period_end = datetime.date(2026, 2, 28)
        collection_date = timezone.localdate() + datetime.timedelta(days=30)
        for i in range(n_charges):
            _make_planned_charge(
                member,
                subscription,
                due_date=period_start + datetime.timedelta(days=i),
            )
        schema_name = connection.schema_name

        n_workers = 8
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = [
                pool.submit(
                    _create_run_in_thread,
                    schema_name,
                    period_start,
                    period_end,
                    collection_date,
                )
                for _ in range(n_workers)
            ]
            results = [f.result() for f in as_completed(futures)]

        winners = [(pk, cc) for (pk, cc) in results if pk is not None]
        assert winners, "no BillingRun was created under concurrency"

        # Every eligible charge is bundled into exactly one run...
        assert (
            ChargeSchedule.objects.filter(billing_run__isnull=True).count() == 0
        ), "some charges were left unbundled"
        assert (
            ChargeSchedule.objects.filter(billing_run__isnull=False).count()
            == n_charges
        )
        # ...and no charge is counted twice. WITHOUT the row lock, two runs
        # bundle overlapping charges and the charge_counts sum above N.
        assert (
            sum(cc for (_pk, cc) in winners) == n_charges
        ), "double-bundling: runs' charge_counts exceed the charge total"
        # The DB partitions the charges across exactly the winner runs.
        assert BillingRun.objects.count() == len(winners)
        bundled_run_ids = set(
            ChargeSchedule.objects.filter(billing_run__isnull=False).values_list(
                "billing_run_id", flat=True
            )
        )
        assert bundled_run_ids == {pk for (pk, _cc) in winners}

    def test_serial_baseline_still_bundles(
        self, tenant, member, subscription, billing_profile
    ):
        """A single create_run still bundles every eligible charge — catches a
        concurrency fix that broke the single-writer path."""
        n_charges = 5
        period_start = datetime.date(2026, 2, 1)
        for i in range(n_charges):
            _make_planned_charge(
                member,
                subscription,
                due_date=period_start + datetime.timedelta(days=i),
            )
        run = BillingRunService.create_run(
            period_start=period_start,
            period_end=datetime.date(2026, 2, 28),
            collection_date=timezone.localdate() + datetime.timedelta(days=30),
        )
        assert run.charge_count == n_charges
        assert ChargeSchedule.objects.filter(billing_run=run).count() == n_charges
