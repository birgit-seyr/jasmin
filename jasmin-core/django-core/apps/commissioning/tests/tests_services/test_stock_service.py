"""Tests for StockService.get_theoretical_current_stock."""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal

import pytest
from django.utils.timezone import make_aware
from isoweek import Week

from apps.commissioning.services.stock_service import StockService
from apps.commissioning.tests.factories import (
    MovementShareArticleFactory,
    ShareArticleFactory,
    StockSnapshotFactory,
    StorageFactory,
)


def _dt(year, week, day_index, hour=12):
    """Build an aware datetime from ISO year/week/day."""
    w = Week(year, week)
    attrs = (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    )
    d = getattr(w, attrs[day_index])()
    return make_aware(datetime.combine(d, time(hour, 0)))


@pytest.mark.django_db
class TestGetTheoreticalCurrentStock:
    def test_empty_returns_empty(self, tenant):
        result = StockService.get_theoretical_current_stock(2026, 15, 2)
        assert result == {}

    def test_single_movement(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("25"),
            movement_type="INVENTORY",
            date=_dt(2026, 15, 1),  # Tuesday
        )

        result = StockService.get_theoretical_current_stock(2026, 15, 2)

        key = (str(article.pk), "KG", "M", str(storage.pk))
        assert key in result
        assert result[key]["theoretical_current_stock"] == 25.0

    def test_snapshot_baseline_plus_movements(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)

        # Snapshot with baseline 100 at start of week
        snap_dt = _dt(2026, 15, 0, hour=6)
        StockSnapshotFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            balance=Decimal("100"),
            snapshot_date=snap_dt,
        )

        # Movement AFTER snapshot: +30
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("30"),
            movement_type="INVENTORY",
            date=_dt(2026, 15, 1),
        )

        result = StockService.get_theoretical_current_stock(2026, 15, 2)

        key = (str(article.pk), "KG", "M", str(storage.pk))
        assert key in result
        # baseline 100 + movement 30 = 130
        assert result[key]["theoretical_current_stock"] == 130.0

    def test_movements_before_snapshot_are_ignored(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)

        snap_dt = _dt(2026, 15, 1, hour=12)
        StockSnapshotFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            balance=Decimal("50"),
            snapshot_date=snap_dt,
        )

        # Movement BEFORE snapshot — should be ignored
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("999"),
            movement_type="INVENTORY",
            date=_dt(2026, 15, 0, hour=6),
        )

        result = StockService.get_theoretical_current_stock(2026, 15, 2)

        key = (str(article.pk), "KG", "M", str(storage.pk))
        # Only the snapshot baseline, old movement excluded
        assert result[key]["theoretical_current_stock"] == 50.0

    def test_inventory_movement_separated(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)

        # Non-inventory movement: +20 (use INVENTORY to avoid source FK requirement)
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("20"),
            movement_type="INVENTORY",
            date=_dt(2026, 15, 1),
        )

        # INVENTORY movement on target day: +5 delta, a REAL count of 25
        # (counted_amount set — the "this is a count" signal the read path and
        # the snapshot cascade both key on).
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("5"),
            counted_amount=Decimal("25"),
            movement_type="INVENTORY",
            date=_dt(2026, 15, 2),
        )

        result = StockService.get_theoretical_current_stock(2026, 15, 2)

        key = (str(article.pk), "KG", "M", str(storage.pk))
        # theoretical = running_balance - inventory_delta = (20+5) - 5 = 20
        assert result[key]["theoretical_current_stock"] == 20.0
        # counted = running_balance = 25
        assert result[key]["current_stock_amount"] == 25.0

    def test_respects_storage_filter(self, tenant):
        article = ShareArticleFactory()
        s1 = StorageFactory(is_short_term_harvest_storage=True)
        s2 = StorageFactory()

        MovementShareArticleFactory(
            share_article=article,
            storage=s1,
            unit="KG",
            size="M",
            amount=Decimal("10"),
            movement_type="INVENTORY",
            date=_dt(2026, 15, 1),
        )
        MovementShareArticleFactory(
            share_article=article,
            storage=s2,
            unit="KG",
            size="M",
            amount=Decimal("30"),
            movement_type="INVENTORY",
            date=_dt(2026, 15, 1),
        )

        result = StockService.get_theoretical_current_stock(
            2026,
            15,
            2,
            storage=str(s1.pk),
        )

        assert len(result) == 1
        key = (str(article.pk), "KG", "M", str(s1.pk))
        assert result[key]["theoretical_current_stock"] == 10.0

    def test_metadata_only_inventory_reads_as_uncounted(self, tenant):
        """goods-flow audit #2 (read side): a metadata-only INVENTORY row
        (counted_amount IS NULL — flags toggled, no count) reads as UNcounted
        (current_stock_amount=None), NOT a phantom count equal to theoretical.
        The flag stays visible; is_finalized reflects the row (False here)."""
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        # Balance seed (+50) on an earlier day — feeds the running balance but is
        # not part of the target day's inventory map.
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("50"),
            movement_type="INVENTORY",
            date=_dt(2026, 15, 0),
        )
        # Metadata-only row ON the target day: zero delta, no count, washed=True.
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            amount=Decimal("0"),
            counted_amount=None,
            washed=True,
            movement_type="INVENTORY",
            date=_dt(2026, 15, 2),
        )

        result = StockService.get_theoretical_current_stock(2026, 15, 2)
        key = (str(article.pk), "KG", "M", str(storage.pk))
        assert result[key]["theoretical_current_stock"] == 50.0
        assert result[key]["current_stock_amount"] is None  # NOT a phantom 50
        assert result[key]["washed"] is True
        assert result[key]["is_finalized"] is False


@pytest.mark.django_db
class TestGetTheoreticalCurrentStockFastPath:
    """When target_date == today, the service reads from CurrentStockBalance
    instead of summing the full movement ledger."""

    def test_reads_from_projection_for_today(self, tenant):
        import time_machine

        from apps.commissioning.tests.factories import CurrentStockBalanceFactory

        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)

        # Freeze time to a known day, then create the projection row for it
        with time_machine.travel(_dt(2026, 20, 1, hour=10), tick=False):
            # Seed a maintained balance directly — no movement on this day yet
            CurrentStockBalanceFactory(
                share_article=article,
                storage=storage,
                unit="KG",
                size="M",
                balance=Decimal("42.000"),
            )
            # Insert an UNRELATED movement on a PAST date — the slow path would
            # see it, the fast path should not (it reads the projection)
            MovementShareArticleFactory(
                share_article=article,
                storage=storage,
                unit="KG",
                size="M",
                amount=Decimal("999"),
                movement_type="INVENTORY",
                date=_dt(2026, 15, 1),
            )

            # day_number=1 (Tuesday of week 20) == today
            result = StockService.get_theoretical_current_stock(2026, 20, 1)

            key = (str(article.pk), "KG", "M", str(storage.pk))
            # Fast path returned the projection value (42), not the legacy
            # sum-of-movements which would be 999
            assert result[key]["theoretical_current_stock"] == 42.0
            assert result[key]["current_stock_amount"] is None  # no INV today

    def test_today_inventory_delta_subtracted_from_theoretical(self, tenant):
        import time_machine

        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)

        with time_machine.travel(_dt(2026, 20, 1, hour=10), tick=False):
            from apps.commissioning.tests.factories import (
                CurrentStockBalanceFactory,
            )

            CurrentStockBalanceFactory(
                share_article=article,
                storage=storage,
                unit="KG",
                size="M",
                balance=Decimal("30.000"),  # post-correction current balance
            )
            # Today's INVENTORY with a +5 correction → theoretical (pre-corr) is 25.
            # A REAL count of 30 (counted_amount set — the "this is a count" signal).
            MovementShareArticleFactory(
                share_article=article,
                storage=storage,
                unit="KG",
                size="M",
                amount=Decimal("5"),
                counted_amount=Decimal("30"),
                movement_type="INVENTORY",
                date=_dt(2026, 20, 1, hour=8),
            )

            result = StockService.get_theoretical_current_stock(2026, 20, 1)

            key = (str(article.pk), "KG", "M", str(storage.pk))
            assert result[key]["theoretical_current_stock"] == 25.0
            assert result[key]["current_stock_amount"] == 30.0
