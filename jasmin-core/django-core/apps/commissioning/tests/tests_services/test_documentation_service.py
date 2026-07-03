"""Tests for GenericDocumentationService."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.commissioning.models import Harvest, MovementShareArticle, Purchase, Waste
from apps.commissioning.services.documentation_service import (
    GenericDocumentationService,
)
from apps.commissioning.tests.factories import (
    HarvestFactory,
    ShareArticleFactory,
    StorageFactory,
)


def _harvest_data(*, article=None, storage=None, amount=None, **overrides):
    """Return validated_data dict suitable for Harvest creation."""
    if article is None:
        article = ShareArticleFactory()
    if storage is None:
        storage = StorageFactory(is_short_term_harvest_storage=True)
    data = {
        "year": 2026,
        "delivery_week": 15,
        "day_number": 1,
        "share_article": article,
        "unit": "KG",
        "size": "M",
        "amount": amount,
        "note": "",
        f"storage_{storage.pk}": True,
    }
    data.update(overrides)
    return data


def _purchase_data(*, article=None, storage=None, amount=None, **overrides):
    if article is None:
        article = ShareArticleFactory(is_purchased=True)
    if storage is None:
        storage = StorageFactory(is_short_term_harvest_storage=True)
    data = {
        "year": 2026,
        "delivery_week": 15,
        "share_article": article,
        "unit": "KG",
        "size": "M",
        "amount": amount,
        "note": "",
        f"storage_{storage.pk}": True,
    }
    data.update(overrides)
    return data


def _waste_data(*, article=None, storage=None, amount=Decimal("5"), **overrides):
    if article is None:
        article = ShareArticleFactory()
    if storage is None:
        storage = StorageFactory(is_short_term_harvest_storage=True)
    data = {
        "year": 2026,
        "delivery_week": 15,
        "day_number": 1,
        "share_article": article,
        "storage": storage,
        "unit": "KG",
        "size": "M",
        "amount": amount,
        "note": "",
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# create_with_related_objects
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateWithRelatedObjects:
    def test_creates_harvest_and_movement(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        data = _harvest_data(article=article, storage=storage, amount=Decimal("20"))

        instance = GenericDocumentationService.create_with_related_objects(
            Harvest, data
        )

        assert instance.pk is not None
        assert instance.share_article == article
        assert instance.storage == storage
        # A movement should have been created
        assert MovementShareArticle.objects.filter(harvest=instance).exists()

    def test_creates_purchase_and_movement(self, tenant):
        article = ShareArticleFactory(is_purchased=True)
        storage = StorageFactory(is_short_term_harvest_storage=True)
        data = _purchase_data(article=article, storage=storage, amount=Decimal("30"))

        instance = GenericDocumentationService.create_with_related_objects(
            Purchase, data
        )

        assert instance.pk is not None
        assert MovementShareArticle.objects.filter(purchase=instance).exists()

    def test_waste_movement_negates_amount(self, tenant):
        data = _waste_data(amount=Decimal("10"))

        instance = GenericDocumentationService.create_with_related_objects(Waste, data)

        movement = MovementShareArticle.objects.get(waste=instance)
        assert movement.amount == Decimal("-10")

    def test_placeholder_harvest_skips_movement(self, tenant):
        """Harvest on short-term storage with amount=None → no movement."""
        storage = StorageFactory(is_short_term_harvest_storage=True)
        data = _harvest_data(storage=storage, amount=None)

        instance = GenericDocumentationService.create_with_related_objects(
            Harvest, data
        )

        assert instance.pk is not None
        assert not MovementShareArticle.objects.filter(harvest=instance).exists()

    def test_harvest_on_non_short_term_storage(self, tenant):
        """Regular storage → amount used directly, no correction mode."""
        storage = StorageFactory(is_short_term_harvest_storage=False)
        data = _harvest_data(storage=storage, amount=Decimal("15"))

        instance = GenericDocumentationService.create_with_related_objects(
            Harvest, data
        )

        movement = MovementShareArticle.objects.get(harvest=instance)
        assert movement.amount == Decimal("15")
        assert movement.counted_amount is None


# ---------------------------------------------------------------------------
# update_with_related_objects
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUpdateWithRelatedObjects:
    def test_updates_fields_and_recreates_movement(self, tenant):
        """Updating amount should delete old movement and create a new one."""
        storage = StorageFactory(is_short_term_harvest_storage=False)
        data = _harvest_data(storage=storage, amount=Decimal("10"))
        instance = GenericDocumentationService.create_with_related_objects(
            Harvest, data
        )
        old_movement_id = MovementShareArticle.objects.get(harvest=instance).pk

        update_data = {"amount": Decimal("25")}
        GenericDocumentationService.update_with_related_objects(instance, update_data)

        instance.refresh_from_db()
        assert instance.amount == Decimal("25")
        new_movement = MovementShareArticle.objects.get(harvest=instance)
        assert new_movement.pk != old_movement_id
        assert new_movement.amount == Decimal("25")

    def test_waste_update_negates(self, tenant):
        data = _waste_data(amount=Decimal("5"))
        instance = GenericDocumentationService.create_with_related_objects(Waste, data)

        GenericDocumentationService.update_with_related_objects(
            instance, {"amount": Decimal("8")}
        )

        movement = MovementShareArticle.objects.get(waste=instance)
        assert movement.amount == Decimal("-8")


# ---------------------------------------------------------------------------
# Correction mode (short-term storage)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCorrectionMode:
    def test_correction_subtracts_theoretical_sum(self, tenant):
        """On short-term storage, movement.amount = counted_amount − Σ theoretical."""
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)

        # Create a theoretical movement for the same dimension.
        # Use a separate Harvest (day=2) to avoid unique_together conflict
        # with the actual Harvest (day=1) created below.
        import datetime as _dt

        from django.utils import timezone as _tz
        from isoweek import Week

        week = Week(2026, 15)
        movement_date = _tz.make_aware(
            _dt.datetime.combine(week.tuesday(), _dt.time(12, 0, 0))
        )

        theoretical_harvest = HarvestFactory(
            share_article=article,
            storage=storage,
            amount=Decimal("30"),
            year=2026,
            delivery_week=15,
            day_number=2,
        )
        MovementShareArticle.objects.create(
            date=movement_date,
            movement_type="HARVEST",
            share_article=article,
            amount=Decimal("30"),
            unit="KG",
            size="M",
            storage=storage,
            is_theoretical=True,
            harvest=theoretical_harvest,
        )

        # Now create the actual Harvest with counted amount = 50
        data = _harvest_data(
            article=article,
            storage=storage,
            amount=Decimal("50"),
        )
        instance = GenericDocumentationService.create_with_related_objects(
            Harvest, data
        )

        movement = MovementShareArticle.objects.get(harvest=instance)
        # amount = counted(50) − theoretical_sum(30) = 20
        assert movement.counted_amount == Decimal("50")
        assert movement.amount == Decimal("20")
