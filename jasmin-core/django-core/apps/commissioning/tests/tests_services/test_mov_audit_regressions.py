"""Regression tests for the movement-logic audit (MOV-1, MOV-2, MOV-3, MOV-6,
MOV-8). MOV-4/MOV-5 are covered by test_current_balance_service; MOV-7/MOV-9 are
concurrency/view-level and exercised by the broader suite.

The HIGH/MED fixes are tested at the mechanism level (the gate, the day-scoped
theoretical sum, the DB constraint) rather than through the full theoretical →
actual → balance chain, whose fixtures (harvest_size, RequiresShortTermStorage,
date derivation) make an end-to-end assertion brittle.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.commissioning.models import (
    CleanAmount,
    Harvest,
    MovementShareArticle,
    TheoreticalHarvest,
    WashAmount,
)
from apps.commissioning.services.documentation_service import (
    GenericDocumentationService,
)
from apps.commissioning.services.snapshot_service import SnapshotService
from apps.commissioning.services.theoretical_objects import (
    TheoreticalSourceData,
    create_theoretical_objects,
)
from apps.commissioning.tests.factories import (
    ShareArticleFactory,
    ShareContentFactory,
    StorageFactory,
)


def _theoretical_harvest_movement(article, storage, *, amount, day, size="M"):
    """Create a theoretical HARVEST movement (and its TheoreticalHarvest) at the
    same noon datetime an actual correction for that (year, week, day) would use."""
    th = TheoreticalHarvest.objects.create(
        year=2026,
        delivery_week=15,
        day_number=day,
        share_article=article,
        unit="KG",
        size=size,
        storage=storage,
        amount=Decimal(amount),
    )
    return MovementShareArticle.objects.create(
        movement_type="HARVEST",
        is_theoretical=True,
        theoretical_harvest=th,
        share_article=article,
        unit="KG",
        size=size,
        storage=storage,
        amount=Decimal(amount),
        date=GenericDocumentationService._movement_datetime(2026, 15, day),
    )


@pytest.mark.django_db
class TestMov1CarriesTheoreticals:
    def test_gate_includes_long_term_harvest_storage(self, tenant):
        """MOV-1: the correction gate must fire for BOTH short- AND long-term
        harvest storage (a comes_from_long_term line plans its harvest on the
        long-term storage), else the actual double-counts the theoretical."""
        short_term = StorageFactory(is_short_term_harvest_storage=True)
        long_term = StorageFactory(
            is_short_term_harvest_storage=False, is_long_term_harvest_storage=True
        )
        other = StorageFactory(
            is_short_term_harvest_storage=False, is_long_term_harvest_storage=False
        )
        carries = GenericDocumentationService._carries_theoreticals

        assert carries(Harvest(storage=short_term)) is True
        assert carries(Harvest(storage=long_term)) is True
        assert carries(Harvest(storage=other)) is False
        assert carries(Harvest(storage=None)) is False


@pytest.mark.django_db
class TestMov2WashCleanPlaceholderStorage:
    def test_placeholders_land_on_short_term_for_long_term_line(self, tenant):
        """MOV-2: the wash/clean ACTUAL placeholders for a long-term line must
        share their theoretical's SHORT-term storage, not the long-term one."""
        article = ShareArticleFactory()
        short_term = StorageFactory(is_short_term_harvest_storage=True)
        long_term = StorageFactory(
            is_short_term_harvest_storage=False, is_long_term_harvest_storage=True
        )
        sc = ShareContentFactory(share_article=article)

        src = TheoreticalSourceData(
            year=2026,
            delivery_week=15,
            delivery_day=2,
            harvesting_day=1,
            washing_day=1,
            cleaning_day=1,
            share_article=article,
            amount=Decimal("10.000"),
            unit="KG",
            size="M",
            note=None,
            washing=True,
            cleaning=True,
            forecast=None,
            is_purchased=False,
            share_content=sc,
            storage=long_term,
            comes_from_long_term_storage=True,
            total_amount_for_shares=Decimal("10.000"),
        )
        create_theoretical_objects([src], create_placeholders=True)

        assert WashAmount.objects.get(share_article=article).storage_id == short_term.id
        assert (
            CleanAmount.objects.get(share_article=article).storage_id == short_term.id
        )


@pytest.mark.django_db
class TestMov3DayScopedTheoreticalSum:
    def test_sum_nets_only_the_corrections_own_day(self, tenant):
        """MOV-3: _sum_theoretical must net only the theoretical(s) for the
        correction's OWN harvesting day. A cumulative date<= summed every earlier
        day's plan too, so a later correction subtracted an already-consumed
        theoretical (total too low + negative HARVEST rows)."""
        article = ShareArticleFactory()
        short_term = StorageFactory(is_short_term_harvest_storage=True)

        _theoretical_harvest_movement(article, short_term, amount="30", day=1)
        _theoretical_harvest_movement(article, short_term, amount="20", day=3)

        day3 = GenericDocumentationService._movement_datetime(2026, 15, 3)
        with transaction.atomic():  # _sum_theoretical takes an advisory xact lock
            total = GenericDocumentationService._sum_theoretical(
                share_article_id=str(article.id),
                unit="KG",
                size="M",
                storage_id=str(short_term.id),
                movement_type="HARVEST",
                up_to=day3,
            )
        # Only day 3's theoretical (20) — NOT day1 + day3 (50).
        assert total == Decimal("20")

        day1 = GenericDocumentationService._movement_datetime(2026, 15, 1)
        with transaction.atomic():
            total_day1 = GenericDocumentationService._sum_theoretical(
                share_article_id=str(article.id),
                unit="KG",
                size="M",
                storage_id=str(short_term.id),
                movement_type="HARVEST",
                up_to=day1,
            )
        assert total_day1 == Decimal("30")


@pytest.mark.django_db
class TestMov6InventoryUniqueness:
    def test_duplicate_inventory_per_entity_day_rejected_at_db(self, tenant):
        """MOV-6: the DB constraint rejects a second INVENTORY for the same
        (entity, day). bulk_create bypasses full_clean so this exercises the
        actual DB-level guard (the concurrency backstop), not just validation."""
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        dt = timezone.make_aware(_dt.datetime(2026, 4, 8, 23, 0, 0))

        MovementShareArticle.objects.create(
            movement_type="INVENTORY",
            share_article=article,
            unit="KG",
            size="M",
            storage=storage,
            date=dt,
            amount=Decimal("5"),
            counted_amount=Decimal("5"),
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            MovementShareArticle.objects.bulk_create(
                [
                    MovementShareArticle(
                        movement_type="INVENTORY",
                        share_article=article,
                        unit="KG",
                        size="M",
                        storage=storage,
                        date=dt,
                        amount=Decimal("3"),
                        counted_amount=Decimal("3"),
                    )
                ]
            )


@pytest.mark.django_db
class TestMov8CascadePreservesNullCounted:
    def test_null_counted_inventory_delta_is_preserved(self, tenant):
        """MOV-8: cascade_future_inventories must NOT zero a future INVENTORY it
        can't recompute (counted_amount is NULL) — it left it at amount=0 forever."""
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        dt = timezone.make_aware(_dt.datetime(2026, 4, 8, 23, 0, 0))

        inv = MovementShareArticle.objects.create(
            movement_type="INVENTORY",
            share_article=article,
            unit="KG",
            size="M",
            storage=storage,
            date=dt,
            amount=Decimal("5"),
            counted_amount=None,
        )

        SnapshotService.cascade_future_inventories(
            str(article.id),
            "KG",
            "M",
            str(storage.id),
            after_date=dt - _dt.timedelta(days=1),
        )

        inv.refresh_from_db()
        assert inv.amount == Decimal("5")  # preserved, not zeroed
