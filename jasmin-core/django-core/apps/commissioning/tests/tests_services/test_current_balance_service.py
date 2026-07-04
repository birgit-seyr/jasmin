"""Tests for CurrentBalanceService — the maintained current-balance projection."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.commissioning.models import CurrentStockBalance, StockSnapshot
from apps.commissioning.services import CurrentBalanceService, SnapshotService
from apps.commissioning.tests.factories import (
    CurrentStockBalanceFactory,
    MovementShareArticleFactory,
    ShareArticleFactory,
    StorageFactory,
)


def _ts(year, month, day, hour=12):
    return timezone.make_aware(datetime.datetime(year, month, day, hour, 0, 0))


@pytest.mark.django_db
class TestRecomputeForEntity:
    def test_creates_row_when_missing(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("12.000"),
            date=_ts(2026, 5, 1),
            movement_type="INVENTORY",
        )

        CurrentBalanceService.recompute_for_entity(article.id, "KG", "M", storage.id)

        row = CurrentStockBalance.objects.get(
            share_article=article, unit="KG", size="M", storage=storage
        )
        assert row.balance == Decimal("12.000")

    def test_updates_existing_row(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        CurrentStockBalanceFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            balance=Decimal("999.000"),  # stale value
        )
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("7.000"),
            date=_ts(2026, 5, 1),
            movement_type="INVENTORY",
        )

        CurrentBalanceService.recompute_for_entity(article.id, "KG", "M", storage.id)

        assert CurrentStockBalance.objects.count() == 1
        row = CurrentStockBalance.objects.get()
        assert row.balance == Decimal("7.000")

    def test_null_storage_treated_as_unique(self, tenant):
        """nulls_distinct=False — two rows with storage=NULL would collide."""
        article = ShareArticleFactory()
        MovementShareArticleFactory(
            share_article=article,
            storage=None,
            unit="KG",
            size="M",
            amount=Decimal("3.000"),
            date=_ts(2026, 5, 1),
            movement_type="INVENTORY",
        )

        CurrentBalanceService.recompute_for_entity(article.id, "KG", "M", None)
        CurrentBalanceService.recompute_for_entity(article.id, "KG", "M", None)

        # Second call must UPDATE the first row, not insert a duplicate
        assert (
            CurrentStockBalance.objects.filter(
                share_article=article, unit="KG", size="M", storage__isnull=True
            ).count()
            == 1
        )


@pytest.mark.django_db
class TestGetDrift:
    def test_no_drift_when_consistent(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("10.000"),
            date=_ts(2026, 5, 1),
            movement_type="INVENTORY",
        )
        CurrentBalanceService.recompute_for_entity(article.id, "KG", "M", storage.id)

        assert CurrentBalanceService.get_drift() == []

    def test_detects_stale_row(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("10.000"),
            date=_ts(2026, 5, 1),
            movement_type="INVENTORY",
        )
        # Pretend the projection drifted (e.g. bypassed write path)
        CurrentStockBalanceFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            balance=Decimal("999.000"),
        )

        drift = CurrentBalanceService.get_drift()
        assert len(drift) == 1
        assert drift[0]["stored"] == Decimal("999.000")
        assert drift[0]["expected"] == Decimal("10.000")


@pytest.mark.django_db
class TestReconcilerSelfConsistency:
    """REF-7: get_drift's 'expected' (raw ledger sum) and the --fix repair must
    compute the SAME quantity, or repair never converges on a corrupt snapshot.
    Also: a ledger entity with no projection row must be detectable."""

    def test_from_ledger_repair_converges_despite_corrupt_snapshot(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        for day, amt in ((1, "10.000"), (10, "5.000")):  # true ledger total = 15
            MovementShareArticleFactory(
                share_article=article,
                storage=storage,
                unit="KG",
                size="M",
                amount=Decimal(amt),
                date=_ts(2026, 5, day),
                movement_type="INVENTORY",
            )
        # A CORRUPT snapshot: claims balance 100 at 05-05 (truth there is 10).
        StockSnapshot.objects.create(
            share_article=article,
            unit="KG",
            size="M",
            storage=storage,
            snapshot_date=_ts(2026, 5, 5),
            balance=Decimal("100.000"),
        )
        # Snapshot-baselined recompute would write 100 + 5 = 105 (the bug).
        snapshot_based = SnapshotService.compute_balance(
            article.id, "KG", "M", storage.id
        )
        assert snapshot_based == Decimal("105.000")

        # from_ledger=True ignores the corrupt snapshot → true raw sum (15).
        row = CurrentBalanceService.recompute_for_entity(
            article.id, "KG", "M", storage.id, from_ledger=True
        )
        assert row.balance == Decimal("15.000")
        # ...and get_drift (also raw-ledger) now agrees → loop converged.
        assert CurrentBalanceService.get_drift() == []

    def test_detects_entity_missing_a_projection_row(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("6.000"),
            date=_ts(2026, 5, 1),
            movement_type="INVENTORY",
        )
        # No CurrentStockBalance row exists for this ledger entity.
        assert not CurrentStockBalance.objects.exists()

        drift = CurrentBalanceService.get_drift()
        assert len(drift) == 1
        assert drift[0]["stored"] is None
        assert drift[0]["expected"] == Decimal("6.000")

        # --fix path seeds the missing row.
        CurrentBalanceService.recompute_for_entity(
            *drift[0]["entity"], from_ledger=True
        )
        assert CurrentBalanceService.get_drift() == []


@pytest.mark.django_db
class TestCascadeHookUpdatesBalance:
    """The real chokepoint integration — cascade_future_inventories must
    refresh CurrentStockBalance even when there are no future inventories
    to cascade."""

    def test_cascade_refreshes_balance_no_future_inventories(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        # Seed a stale projection
        CurrentStockBalanceFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            balance=Decimal("0.000"),
        )
        # Add an INVENTORY movement (counted_amount set so cascade can keep
        # the delta consistent if it lands in `future_inventories`)
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("8.000"),
            counted_amount=Decimal("8.000"),
            date=_ts(2026, 5, 1),
            movement_type="INVENTORY",
        )
        # after_date AFTER the movement → no future inventories to recompute,
        # the cascade just refreshes the projection at the end.
        SnapshotService.cascade_future_inventories(
            article.id, "KG", "M", storage.id, after_date=_ts(2026, 6, 1)
        )

        row = CurrentStockBalance.objects.get(
            share_article=article, unit="KG", size="M", storage=storage
        )
        assert row.balance == Decimal("8.000")


@pytest.mark.django_db
class TestSnapshotDrift:
    """Audit #7: reconcile must also detect + repair corrupt ``StockSnapshot``
    baselines, not just the current-balance projection — a snapshot wrong at its
    own date re-drifts every future ``from_ledger=False`` recompute and every
    historical ``compute_balance(up_to=...)`` even when the current total is fine.
    """

    def _corrupt_fixture(self, article, storage):
        # True ledger: +10 @ 05-01, +5 @ 05-10 → total 15; truth @ 05-05 is 10.
        for day, amt in ((1, "10.000"), (10, "5.000")):
            MovementShareArticleFactory(
                share_article=article,
                storage=storage,
                unit="KG",
                size="M",
                amount=Decimal(amt),
                date=_ts(2026, 5, day),
                movement_type="INVENTORY",
            )
        # A CORRUPT snapshot: claims 100 @ 05-05 (truth there is 10).
        StockSnapshot.objects.create(
            share_article=article,
            unit="KG",
            size="M",
            storage=storage,
            snapshot_date=_ts(2026, 5, 5),
            balance=Decimal("100.000"),
        )

    def test_get_snapshot_drift_flags_corrupt_snapshot(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        self._corrupt_fixture(article, storage)

        drift = CurrentBalanceService.get_snapshot_drift()
        assert len(drift) == 1
        assert drift[0]["stored"] == Decimal("100.000")
        assert drift[0]["expected"] == Decimal("10.000")  # true ledger @ 05-05
        assert drift[0]["entity"] == (str(article.id), "KG", "M", str(storage.id))

    def test_no_snapshot_drift_when_consistent(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("10.000"),
            date=_ts(2026, 5, 1),
            movement_type="INVENTORY",
        )
        SnapshotService.create_snapshot_for_entity(
            article.id, "KG", "M", storage.id, snapshot_date=_ts(2026, 5, 5)
        )
        assert CurrentBalanceService.get_snapshot_drift() == []

    def test_repair_clears_drift_and_survives_recompute(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        self._corrupt_fixture(article, storage)
        # The corrupt baseline makes a snapshot-based recompute wrong (100 + 5).
        assert SnapshotService.compute_balance(
            article.id, "KG", "M", storage.id
        ) == Decimal("105.000")

        CurrentBalanceService.repair_snapshots_for_entity(
            article.id, "KG", "M", storage.id
        )

        assert CurrentBalanceService.get_snapshot_drift() == []
        # A subsequent snapshot-baselined recompute no longer re-drifts.
        assert SnapshotService.compute_balance(
            article.id, "KG", "M", storage.id
        ) == Decimal("15.000")
        assert CurrentBalanceService.get_drift() == []

    def test_repair_fixes_historical_query(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        self._corrupt_fixture(article, storage)
        # Before: a historical query at 05-06 reads the corrupt 05-05 baseline.
        assert SnapshotService.compute_balance(
            article.id, "KG", "M", storage.id, up_to=_ts(2026, 5, 6)
        ) == Decimal("100.000")

        CurrentBalanceService.repair_snapshots_for_entity(
            article.id, "KG", "M", storage.id
        )

        # After: no snapshot at/before 05-06 → falls back to the raw ledger → 10.
        assert SnapshotService.compute_balance(
            article.id, "KG", "M", storage.id, up_to=_ts(2026, 5, 6)
        ) == Decimal("10.000")

    def test_reconcile_command_fix_repairs_snapshots(self, tenant):
        from io import StringIO

        from django.core.management import call_command

        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        self._corrupt_fixture(article, storage)
        assert CurrentBalanceService.get_snapshot_drift()  # drift present

        call_command("reconcile_current_stock", "--fix", stdout=StringIO())

        assert CurrentBalanceService.get_snapshot_drift() == []
