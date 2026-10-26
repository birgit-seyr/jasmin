"""Concurrency tests for ``BillingRunService.create_run`` and ``export``.

``create_run`` selects eligible PLANNED charges (``billing_run__isnull=True``)
and assigns each to a new ``BillingRun`` inside ``@transaction.atomic``. Under
Postgres READ COMMITTED, two concurrent runs over an overlapping period could
both read the same unassigned charges and bundle them into two different runs
— double-charging a member's SEPA mandate (the second writer silently
overwrites the first run's FK pointer while the first run's ``charge_count`` /
total still counted them). Runs therefore take a tenant-local advisory lock:
the second waits for the first and finds its charges taken.

A re-plan (a subscription change, a pause edit, "Regenerate charges") holds a
subscription's PLANNED rows until it commits. ``create_run`` passes over them
with ``skip_locked`` and refuses the run as retryable instead of leaving those
charges out. Exporting or deleting a run locks its charges without waiting and
refuses the same way while a re-plan holds one; once the re-plan has dropped a
charge and committed, the export's file leaves it out, and it stays gone.

These tests prove it with real threads (a mocked query wouldn't reproduce the
interleaving), mirroring the invoice/member numbering concurrency tests.
``@pytest.mark.django_db(transaction=True)`` is required: worker threads open
their own connections and can only see COMMITTED rows, and the row locks only
block across committed transactions.
"""

from __future__ import annotations

import datetime
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal

import pytest
from django.db import connection, connections, transaction
from django.utils import timezone

from apps.commissioning.models import ShareTypeVariation, Subscription
from apps.commissioning.tests.factories import (
    PaymentCycleFactory,
    SubscriptionFactory,
)
from apps.payments.constants import BillingRunStatus, ChargeStatus
from apps.payments.errors import BillingRunChargesBeingReplanned
from apps.payments.models import BillingRun, ChargeSchedule
from apps.payments.services import BillingRunService, ChargeScheduleService
from apps.shared.tenants.models import ActionRateLog


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
    sidestep the cross-test collision. The member is created per test, and
    the share-type variation is the one ``_subscription`` shares.
    """
    return _subscription(member)


# The share-type variation this module's subscriptions share. Under
# ``transaction=True`` a factory-made variation is committed and stays, and the
# share type has only a few free sizes for new ones.
_shared_variation: dict[str, str] = {}


def _subscription(member):
    variation = ShareTypeVariation.objects.filter(
        pk=_shared_variation.get("pk")
    ).first()
    subscription = SubscriptionFactory(
        member=member,
        valid_from=datetime.date(2026, 1, 5),
        valid_until=datetime.date(2026, 12, 27),
        quantity=1,
        price_per_delivery=Decimal("10.00"),
        payment_cycle=PaymentCycleFactory(choice="MONTHLY"),
        default_delivery_station_day=None,
        **({"share_type_variation": variation} if variation else {}),
    )
    _shared_variation["pk"] = subscription.share_type_variation_id
    return subscription


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
    ``(None, 0)`` when it found nothing to bundle (a run before it had already
    claimed the charges — a legitimate outcome, NOT an error). Closes
    thread-local connections in a finally, so none outlives the test.
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


def _hold_like_a_replan(schema_name, subscription_pk, holding, release):
    """Worker: a re-plan of the subscription that has taken the lock on its
    PLANNED rows, with the re-plan's own lock step, and keeps it until
    ``release`` is set."""
    from django_tenants.utils import schema_context

    connection.close()
    try:
        with schema_context(schema_name), transaction.atomic():
            subscription = Subscription.objects.get(pk=subscription_pk)
            ChargeScheduleService._lock_and_unbundle_stale_planned(
                subscription, subscription.valid_until
            )
            holding.set()
            assert release.wait(timeout=30)
    finally:
        for conn in connections.all():
            conn.close()


def _hold_like_a_run_in_progress(schema_name, holding, release):
    """Worker: a run being created, which has taken the runs' advisory lock and
    locked the due charges, and finishes only once ``release`` is set. It
    bundles nothing, so the charges are still free for the run after it."""
    from django_tenants.utils import schema_context

    from core.db_locks import acquire_advisory_xact_lock

    connection.close()
    try:
        with schema_context(schema_name), transaction.atomic():
            acquire_advisory_xact_lock("billing_run:create")
            list(
                ChargeSchedule.objects.select_for_update(of=("self",))
                .filter(status=ChargeStatus.PLANNED)
                .values_list("pk", flat=True)
            )
            holding.set()
            assert release.wait(timeout=30)
    finally:
        for conn in connections.all():
            conn.close()


def _drop_like_a_replan(schema_name, charge_pk, dropped, release):
    """Worker: a re-plan that takes a bundled charge out of its DRAFT run and
    deletes it, as a cancellation ending the term before the charge's period
    does, and commits only once ``release`` is set."""
    from django_tenants.utils import schema_context

    connection.close()
    try:
        with schema_context(schema_name), transaction.atomic():
            charges = ChargeSchedule.objects.filter(pk=charge_pk)
            list(charges.select_for_update(of=("self",)).values_list("pk", flat=True))
            charges.update(billing_run=None)
            charges.delete()
            dropped.set()
            assert release.wait(timeout=30)
    finally:
        for conn in connections.all():
            conn.close()


def _wait_for(event, worker, timeout=30.0):
    """Wait until ``worker`` sets ``event``. A worker that fails first raises
    its own error here, rather than the wait timing out."""
    deadline = time.monotonic() + timeout
    while not event.wait(timeout=0.05):
        if worker.done():
            worker.result()
            raise AssertionError("the worker finished without signalling")
        if time.monotonic() > deadline:
            raise AssertionError("the worker never signalled")


def _wait_until_blocked_on_the_runs_lock(worker, timeout=30.0):
    """Return once another session of this database waits for an advisory
    lock: ``worker``'s run, waiting for the run being created before it."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if worker.done():
            worker.result()
            raise AssertionError("the run finished without waiting for the other")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid() "
                "AND wait_event_type = 'Lock' AND wait_event = 'advisory'"
            )
            if cursor.fetchone()[0]:
                return
        time.sleep(0.05)
    raise AssertionError("no run waited for the runs' advisory lock")


def _with_sepa_creditor(tenant):
    """The export reads ``tenant.sepa_creditor_*`` off the IN-MEMORY tenant
    (``tenant_context(tenant)`` in the worker), so they are set directly instead
    of via the shared ``tenant_settings`` fixture: that fixture also INSERTs a
    public ``TenantSettings`` row, which ``transaction=True`` commits and leaves
    in place for every later transactional test. ``create_run`` / ``export``
    don't need a persisted TenantSettings — ``_billing_config`` safely falls
    back to EXACT when none exists."""
    tenant.iban = "DE89370400440532013000"
    tenant.sepa_creditor_id = "DE98ZZZ09999999999"
    tenant.sepa_creditor_name = "Test Farm e.G."
    tenant.sepa_creditor_bic = "COBADEFFXXX"


def _export_in_thread(tenant, run_pk):
    """Worker: fresh connection in the tenant schema, call ``export``.

    Uses ``tenant_context(tenant)`` (not ``schema_context(name)``): the SEPA
    XML builder reads ``connection.tenant.sepa_creditor_*``, which a
    schema-only FakeTenant lacks. Returns ``"exported"`` for the thread that
    produced the file, ``"not_draft"`` for the one that lost the race (the
    run was already EXPORTED by the time it acquired the row lock), or
    ``"busy"`` when a re-plan held one of the run's charges. Closes
    thread-local connections in a finally, so none outlives the test.
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
            except BillingRunChargesBeingReplanned:
                return "busy"
    finally:
        for conn in connections.all():
            conn.close()


def _clear_rate_log(tenant):
    """Drop the tenant's action-quota rows. ``create_run`` and ``export`` write
    one each, ``transaction=True`` commits them and nothing flushes them, so five
    within a minute would block the next run anywhere in the suite."""
    ActionRateLog.objects.filter(tenant_schema=tenant.schema_name).delete()


@pytest.mark.django_db(transaction=True)
class TestBillingRunExportConcurrency:
    """``export`` must serialise on the BillingRun row so two concurrent
    exports of the same DRAFT run can't both emit a valid pain.008 (the
    member would be direct-debited twice if both files reach the bank)."""

    @pytest.fixture(autouse=True)
    def _hermetic_charge_tables(self, tenant):
        ChargeSchedule.objects.all().delete()
        BillingRun.objects.all().delete()
        _clear_rate_log(tenant)
        yield
        _clear_rate_log(tenant)

    def test_concurrent_export_emits_one_file_one_conflict(
        self, tenant, member, subscription, billing_profile
    ):
        _with_sepa_creditor(tenant)

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
        _clear_rate_log(tenant)
        yield
        _clear_rate_log(tenant)

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
        # The runs queue on the advisory lock: the first bundles every charge,
        # and each one after it finds nothing left.
        assert len(winners) == 1, winners

        # Every eligible charge is bundled into exactly one run...
        assert (
            ChargeSchedule.objects.filter(billing_run__isnull=True).count() == 0
        ), "some charges were left unbundled"
        assert (
            ChargeSchedule.objects.filter(billing_run__isnull=False).count()
            == n_charges
        )
        # ...and no charge is counted twice. Without the runs taking turns, two
        # runs bundle overlapping charges and the charge_counts sum above N.
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
        concurrency guard that breaks the single-writer path."""
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


@pytest.mark.django_db(transaction=True)
class TestCreateRunWhileAReplanHoldsCharges:
    """A run created while a re-plan holds charges due in its period is
    refused as retryable: created anyway it would leave those charges out
    without a word, and nothing would prompt the office to collect them."""

    @pytest.fixture(autouse=True)
    def _hermetic_charge_tables(self, tenant):
        ChargeSchedule.objects.all().delete()
        BillingRun.objects.all().delete()
        _clear_rate_log(tenant)
        yield
        _clear_rate_log(tenant)

    def _create_run_while_held(self, subscription):
        holding, release = threading.Event(), threading.Event()
        with ThreadPoolExecutor(max_workers=1) as pool:
            holder = pool.submit(
                _hold_like_a_replan,
                connection.schema_name,
                subscription.pk,
                holding,
                release,
            )
            try:
                _wait_for(holding, holder)
                with pytest.raises(BillingRunChargesBeingReplanned) as refused:
                    _create_february_run()
            finally:
                release.set()
            holder.result()
        return refused.value

    def test_a_run_is_refused_and_creating_it_again_bundles_every_charge(
        self, tenant, member, subscription, billing_profile
    ):
        held = _make_planned_charge(
            member, subscription, due_date=datetime.date(2026, 2, 5)
        )
        free = _make_planned_charge(
            member, _subscription(member), due_date=datetime.date(2026, 2, 12)
        )

        refusal = self._create_run_while_held(subscription)

        assert refusal.details == {"charges": 1}
        assert not BillingRun.objects.exists()
        assert not ChargeSchedule.objects.filter(billing_run__isnull=False).exists()
        run = _create_february_run()
        assert run.charge_count == 2
        assert set(run.charges.values_list("pk", flat=True)) == {held.pk, free.pk}

    def test_held_charges_alone_are_no_reason_to_blame_the_payment_details(
        self, tenant, member, subscription, billing_profile
    ):
        _make_planned_charge(member, subscription, due_date=datetime.date(2026, 2, 5))

        refusal = self._create_run_while_held(subscription)

        assert refusal.code == "billing_run.charges_being_replanned"


@pytest.mark.django_db(transaction=True)
class TestRunsTakeTurns:
    """A run created while another is being created waits for it: it would
    otherwise take the other run's locked charges for a re-plan's and refuse."""

    @pytest.fixture(autouse=True)
    def _hermetic_charge_tables(self, tenant):
        ChargeSchedule.objects.all().delete()
        BillingRun.objects.all().delete()
        _clear_rate_log(tenant)
        yield
        _clear_rate_log(tenant)

    def test_the_second_run_waits_and_bundles_what_the_first_left(
        self, tenant, member, subscription, billing_profile
    ):
        _make_planned_charge(member, subscription, due_date=datetime.date(2026, 2, 5))
        schema_name = connection.schema_name
        holding, release = threading.Event(), threading.Event()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(
                _hold_like_a_run_in_progress, schema_name, holding, release
            )
            try:
                _wait_for(holding, first)
                second = pool.submit(
                    _create_run_in_thread,
                    schema_name,
                    datetime.date(2026, 2, 1),
                    datetime.date(2026, 2, 28),
                    timezone.localdate() + datetime.timedelta(days=30),
                )
                _wait_until_blocked_on_the_runs_lock(second)
            finally:
                release.set()
            first.result()
            run_pk, charge_count = second.result()

        assert run_pk is not None
        assert charge_count == 1


def _create_february_run():
    return BillingRunService.create_run(
        period_start=datetime.date(2026, 2, 1),
        period_end=datetime.date(2026, 2, 28),
        collection_date=timezone.localdate() + datetime.timedelta(days=30),
    )


@pytest.mark.django_db(transaction=True)
class TestExportWhileAReplanDropsACharge:
    """An export that meets a charge a re-plan holds refuses as retryable
    instead of waiting for it. Exported again once the re-plan has dropped the
    charge and committed, the file and the run's totals hold only the charges
    still in the run, and the dropped charge stays deleted."""

    @pytest.fixture(autouse=True)
    def _hermetic_charge_tables(self, tenant):
        ChargeSchedule.objects.all().delete()
        BillingRun.objects.all().delete()
        _clear_rate_log(tenant)
        yield
        _clear_rate_log(tenant)

    def test_the_export_refuses_then_leaves_out_the_dropped_charge(
        self, tenant, member, subscription, billing_profile
    ):
        _with_sepa_creditor(tenant)
        kept = _make_planned_charge(
            member, subscription, due_date=datetime.date(2026, 2, 5)
        )
        dropped_charge = _make_planned_charge(
            member,
            subscription,
            due_date=datetime.date(2026, 3, 5),
            amount=Decimal("30.00"),
        )
        run = BillingRunService.create_run(
            period_start=datetime.date(2026, 2, 1),
            period_end=datetime.date(2026, 3, 31),
            collection_date=timezone.localdate() + datetime.timedelta(days=30),
        )
        assert run.charge_count == 2
        dropped_charge.refresh_from_db()

        dropped, release = threading.Event(), threading.Event()
        with ThreadPoolExecutor(max_workers=2) as pool:
            replan = pool.submit(
                _drop_like_a_replan,
                connection.schema_name,
                dropped_charge.pk,
                dropped,
                release,
            )
            try:
                _wait_for(dropped, replan)
                refused = pool.submit(_export_in_thread, tenant, run.pk).result(
                    timeout=30
                )
            finally:
                release.set()
            replan.result()
            exported = pool.submit(_export_in_thread, tenant, run.pk).result(timeout=30)

        assert refused == "busy"
        assert exported == "exported"
        run.refresh_from_db()
        assert run.status == BillingRunStatus.EXPORTED
        assert run.charge_count == 1
        assert run.total_amount == Decimal("25.00")
        assert not ChargeSchedule.objects.filter(pk=dropped_charge.pk).exists()
        kept.refresh_from_db()
        assert kept.status == ChargeStatus.ISSUED
        with run.sepa_xml_export.open("rb") as xml_file:
            xml = xml_file.read().decode()
        assert kept.end_to_end_id in xml
        assert dropped_charge.end_to_end_id not in xml


@pytest.mark.django_db(transaction=True)
class TestDeleteWhileAReplanHoldsACharge:
    """Deleting a DRAFT run unbundles its charges. A re-plan holding one makes
    the delete refuse as retryable instead of waiting for it; once the re-plan
    has committed, the delete goes through."""

    @pytest.fixture(autouse=True)
    def _hermetic_charge_tables(self, tenant):
        ChargeSchedule.objects.all().delete()
        BillingRun.objects.all().delete()
        _clear_rate_log(tenant)
        yield
        _clear_rate_log(tenant)

    def test_the_delete_refuses_then_goes_through(
        self, tenant, member, subscription, billing_profile
    ):
        charge = _make_planned_charge(
            member, subscription, due_date=datetime.date(2026, 2, 5)
        )
        run = _create_february_run()

        holding, release = threading.Event(), threading.Event()
        with ThreadPoolExecutor(max_workers=1) as pool:
            holder = pool.submit(
                _hold_like_a_replan,
                connection.schema_name,
                subscription.pk,
                holding,
                release,
            )
            try:
                _wait_for(holding, holder)
                with pytest.raises(BillingRunChargesBeingReplanned):
                    BillingRunService.delete_draft(run)
            finally:
                release.set()
            holder.result()

        assert BillingRun.objects.filter(pk=run.pk).exists()
        BillingRunService.delete_draft(run)
        assert not BillingRun.objects.filter(pk=run.pk).exists()
        charge.refresh_from_db()
        assert charge.status == ChargeStatus.PLANNED
        assert charge.billing_run_id is None
