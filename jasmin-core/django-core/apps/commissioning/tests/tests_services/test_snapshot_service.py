"""Tests for SnapshotService."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
import time_machine
from django.utils import timezone

from apps.commissioning.services.snapshot_service import SnapshotService
from apps.commissioning.tests.factories import (
    HarvestFactory,
    MovementShareArticleFactory,
    ShareArticleFactory,
    StockSnapshotFactory,
    StorageFactory,
)


def _ts(year, month, day, hour=12):
    """Convenience helper — timezone-aware datetime."""
    return timezone.make_aware(datetime.datetime(year, month, day, hour, 0, 0))


# ---------------------------------------------------------------------------
# compute_balance
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestComputeBalance:
    def test_empty_movements_returns_zero(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        balance = SnapshotService.compute_balance(article.id, "KG", "M", storage.id)
        assert balance == Decimal("0")

    def test_sums_all_movements(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        dt1 = _ts(2026, 4, 1)
        dt2 = _ts(2026, 4, 2)

        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("10.000"),
            date=dt1,
            movement_type="INVENTORY",
        )
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("5.000"),
            date=dt2,
            movement_type="INVENTORY",
        )

        balance = SnapshotService.compute_balance(article.id, "KG", "M", storage.id)
        assert balance == Decimal("15.000")

    def test_respects_up_to_cutoff(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)

        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("10.000"),
            date=_ts(2026, 4, 1),
            movement_type="INVENTORY",
        )
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("5.000"),
            date=_ts(2026, 4, 5),
            movement_type="INVENTORY",
        )

        balance = SnapshotService.compute_balance(
            article.id,
            "KG",
            "M",
            storage.id,
            up_to=_ts(2026, 4, 3),
        )
        assert balance == Decimal("10.000")

    def test_uses_snapshot_baseline(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)

        StockSnapshotFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            balance=Decimal("100.000"),
            snapshot_date=_ts(2026, 3, 15),
        )
        # Movement AFTER the snapshot
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("7.000"),
            date=_ts(2026, 3, 20),
            movement_type="INVENTORY",
        )
        # Movement BEFORE the snapshot — should be skipped
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("999.000"),
            date=_ts(2026, 3, 10),
            movement_type="INVENTORY",
        )

        balance = SnapshotService.compute_balance(article.id, "KG", "M", storage.id)
        assert balance == Decimal("107.000")


# ---------------------------------------------------------------------------
# create_snapshot_for_entity
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateSnapshotForEntity:
    def test_creates_snapshot_with_correct_balance(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)

        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("25.000"),
            date=_ts(2026, 4, 1),
            movement_type="INVENTORY",
        )

        snap = SnapshotService.create_snapshot_for_entity(
            article.id,
            "KG",
            "M",
            storage.id,
            snapshot_date=_ts(2026, 4, 2),
        )
        assert snap.balance == Decimal("25.000")
        assert snap.share_article_id == article.id

    def test_replaces_existing_snapshot_at_same_date(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        dt = _ts(2026, 4, 1)

        StockSnapshotFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            balance=Decimal("999.000"),
            snapshot_date=dt,
        )
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("10.000"),
            date=_ts(2026, 3, 28),
            movement_type="INVENTORY",
        )

        snap = SnapshotService.create_snapshot_for_entity(
            article.id,
            "KG",
            "M",
            storage.id,
            snapshot_date=dt,
        )
        assert snap.balance == Decimal("10.000")

    @time_machine.travel("2026-04-10 12:00:00+00:00")
    def test_defaults_date_to_now(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)

        snap = SnapshotService.create_snapshot_for_entity(
            article.id,
            "KG",
            "M",
            storage.id,
        )
        assert snap.snapshot_date.date() == datetime.date(2026, 4, 10)


# ---------------------------------------------------------------------------
# delete_snapshots_for_entity
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDeleteSnapshotsForEntity:
    def test_deletes_all_for_entity(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)

        StockSnapshotFactory(
            share_article=article, storage=storage, unit="KG", size="M"
        )
        StockSnapshotFactory(
            share_article=article, storage=storage, unit="KG", size="M"
        )

        count = SnapshotService.delete_snapshots_for_entity(
            article.id,
            "KG",
            "M",
            storage.id,
        )
        assert count == 2

    def test_deletes_within_date_range(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)

        StockSnapshotFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            snapshot_date=_ts(2026, 3, 1),
        )
        StockSnapshotFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            snapshot_date=_ts(2026, 4, 1),
        )
        StockSnapshotFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            snapshot_date=_ts(2026, 5, 1),
        )

        count = SnapshotService.delete_snapshots_for_entity(
            article.id,
            "KG",
            "M",
            storage.id,
            date_from=_ts(2026, 3, 15),
            date_to=_ts(2026, 4, 15),
        )
        assert count == 1  # only April snapshot

    def test_returns_zero_for_no_match(self, tenant):
        article = ShareArticleFactory()
        count = SnapshotService.delete_snapshots_for_entity(
            article.id,
            "KG",
            "M",
            None,
        )
        assert count == 0


# ---------------------------------------------------------------------------
# cascade_future_inventories
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCascadeFutureInventories:
    def test_recalculates_inventory_deltas(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)

        # A harvest movement: +50 (needs a real Harvest source)
        harvest = HarvestFactory(
            share_article=article,
            storage=storage,
            amount=Decimal("50.000"),
        )
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("50.000"),
            date=_ts(2026, 4, 1),
            movement_type="HARVEST",
            harvest=harvest,
        )
        # An INVENTORY at April 5: counted 60 → delta = 60 − 50 = 10
        from apps.commissioning.models import MovementShareArticle

        inv = MovementShareArticle.objects.create(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("10.000"),
            counted_amount=Decimal("60.000"),
            date=_ts(2026, 4, 5),
            movement_type="INVENTORY",
        )

        # Now change the harvest to +30 — the inventory delta should become 60 - 30 = 30
        harvest_mv = MovementShareArticle.objects.filter(
            movement_type="HARVEST"
        ).first()
        harvest_mv.amount = Decimal("30.000")
        harvest_mv.save(update_fields=["amount"])

        updated = SnapshotService.cascade_future_inventories(
            article.id,
            "KG",
            "M",
            storage.id,
            after_date=_ts(2026, 4, 1),
        )
        assert updated == 1

        inv.refresh_from_db()
        assert inv.amount == Decimal("30.000")  # 60 counted − 30 balance_before

    def test_returns_zero_when_no_future_inventories(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)

        updated = SnapshotService.cascade_future_inventories(
            article.id,
            "KG",
            "M",
            storage.id,
            after_date=_ts(2026, 1, 1),
        )
        assert updated == 0


# ---------------------------------------------------------------------------
# cascade_for_movements
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCascadeForMovements:
    def test_groups_by_entity_and_cascades(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)

        mv = MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("10.000"),
            date=_ts(2026, 4, 1),
            movement_type="INVENTORY",
        )

        # Should not raise and returns an int
        total = SnapshotService.cascade_for_movements([mv])
        assert isinstance(total, int)
