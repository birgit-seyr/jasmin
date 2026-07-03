"""Tests for ForecastService."""

from __future__ import annotations

from decimal import Decimal

import pytest
from isoweek import Week

from apps.commissioning.errors import ShareTypeVariationNotFound
from apps.commissioning.models import (
    ForecastOfferGroup,
    ForecastShareTypeVariation,
)
from apps.commissioning.services.forecast_service import ForecastService
from apps.commissioning.tests.factories import (
    ForecastFactory,
    ForecastShareTypeVariationFactory,
    OfferGroupFactory,
    ShareArticleFactory,
    ShareTypeVariationFactory,
    StorageFactory,
)


# ---------------------------------------------------------------------------
# _extract_forecast_fields  (pure — no DB)
# ---------------------------------------------------------------------------
class TestExtractForecastFields:
    def test_filters_known_fields(self):
        data = {
            "amount": Decimal("100"),
            "unit": "KG",
            "size": "M",
            "year": 2026,
            "delivery_week": 15,
            "extra_junk": "ignored",
            "variation_42": True,
        }
        result = ForecastService._extract_forecast_fields(data)
        assert "amount" in result
        assert "unit" in result
        assert "extra_junk" not in result
        assert "variation_42" not in result


# ---------------------------------------------------------------------------
# get_forecasts_with_relations
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetForecastsWithRelations:
    def test_returns_forecast_with_variation_flags(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        forecast = ForecastFactory(
            year=2026, delivery_week=15, share_article=article, storage=storage
        )
        variation = ShareTypeVariationFactory()
        ForecastShareTypeVariationFactory(
            forecast=forecast, share_type_variation=variation
        )

        svc = ForecastService()
        result = svc.get_forecasts_with_relations(2026, 15)

        assert len(result) == 1
        assert result[0]["share_article"] == article.pk
        assert result[0][f"variation_{variation.pk}"] is True

    def test_returns_empty_for_no_data(self, tenant):
        svc = ForecastService()
        result = svc.get_forecasts_with_relations(2026, 99)
        assert result == []

    def test_includes_offer_group_flags(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        forecast = ForecastFactory(
            year=2026, delivery_week=15, share_article=article, storage=storage
        )
        og = OfferGroupFactory()
        ForecastOfferGroup.objects.create(forecast=forecast, offer_group=og)

        svc = ForecastService()
        result = svc.get_forecasts_with_relations(2026, 15)
        assert result[0][f"offer_group_{og.pk}"] is True


# ---------------------------------------------------------------------------
# create_forecast_with_related_objects
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateForecastWithRelatedObjects:
    def test_creates_forecast_and_variations(self, tenant):
        article = ShareArticleFactory()
        variation = ShareTypeVariationFactory()

        data = {
            "year": 2026,
            "delivery_week": 20,
            "share_article": article,
            "amount": Decimal("50"),
            "unit": "KG",
            "size": "M",
            f"variation_{variation.pk}": True,
        }

        svc = ForecastService()
        forecast = svc.create_forecast_with_related_objects(data)

        assert forecast.pk is not None
        assert forecast.amount == Decimal("50")
        assert ForecastShareTypeVariation.objects.filter(
            forecast=forecast, share_type_variation=variation
        ).exists()

    def test_creates_offer_groups(self, tenant):
        article = ShareArticleFactory()
        og = OfferGroupFactory()

        data = {
            "year": 2026,
            "delivery_week": 20,
            "share_article": article,
            "amount": Decimal("30"),
            "unit": "KG",
            "size": "M",
            f"offer_group_{og.pk}": True,
        }

        svc = ForecastService()
        forecast = svc.create_forecast_with_related_objects(data)

        assert ForecastOfferGroup.objects.filter(
            forecast=forecast, offer_group=og
        ).exists()

    def test_raises_for_nonexistent_variation(self, tenant):
        article = ShareArticleFactory()
        data = {
            "year": 2026,
            "delivery_week": 20,
            "share_article": article,
            "amount": Decimal("30"),
            "unit": "KG",
            "size": "M",
            "variation_999999": True,
        }
        svc = ForecastService()
        with pytest.raises(ShareTypeVariationNotFound, match="does not exist"):
            svc.create_forecast_with_related_objects(data)


# ---------------------------------------------------------------------------
# update_forecast_with_related_objects
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUpdateForecastWithRelatedObjects:
    def test_updates_fields_and_variations(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        forecast = ForecastFactory(
            year=2026,
            delivery_week=15,
            share_article=article,
            amount=Decimal("100"),
            storage=storage,
        )
        old_var = ShareTypeVariationFactory()
        ForecastShareTypeVariationFactory(
            forecast=forecast, share_type_variation=old_var
        )

        new_var = ShareTypeVariationFactory()
        data = {
            "amount": Decimal("75"),
            "unit": "KG",
            "size": "M",
            "year": 2026,
            "delivery_week": 15,
            f"variation_{new_var.pk}": True,
        }

        svc = ForecastService()
        updated = svc.update_forecast_with_related_objects(forecast, data)

        assert updated.amount == Decimal("75")
        # Old variation should be removed, new one present
        assert not ForecastShareTypeVariation.objects.filter(
            forecast=forecast, share_type_variation=old_var
        ).exists()
        assert ForecastShareTypeVariation.objects.filter(
            forecast=forecast, share_type_variation=new_var
        ).exists()


# ---------------------------------------------------------------------------
# bulk_copy_forecast_to_next_week
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestBulkCopyForecastToNextWeek:
    def test_copies_to_next_week(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        forecast = ForecastFactory(
            year=2026,
            delivery_week=15,
            share_article=article,
            amount=Decimal("100"),
            unit="KG",
            size="M",
            storage=storage,
        )

        svc = ForecastService()
        new_forecast = svc.bulk_copy_forecast_to_next_week(forecast)

        assert new_forecast is not None
        assert new_forecast.delivery_week == 16
        assert new_forecast.amount == Decimal("100")
        assert new_forecast.share_article == article

    def test_returns_none_when_duplicate_exists(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        forecast = ForecastFactory(
            year=2026,
            delivery_week=15,
            share_article=article,
            unit="KG",
            size="M",
            storage=storage,
        )
        # Create duplicate at week 16
        ForecastFactory(
            year=2026,
            delivery_week=16,
            share_article=article,
            unit="KG",
            size="M",
            storage=storage,
        )

        svc = ForecastService()
        result = svc.bulk_copy_forecast_to_next_week(forecast)
        assert result is None

    def test_year_boundary(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        last_week = Week.last_week_of_year(2026)
        forecast = ForecastFactory(
            year=2026,
            delivery_week=last_week.week,
            share_article=article,
            unit="KG",
            size="M",
            storage=storage,
        )

        svc = ForecastService()
        new_forecast = svc.bulk_copy_forecast_to_next_week(forecast)

        assert new_forecast is not None
        assert new_forecast.year == 2027
        assert new_forecast.delivery_week == 1
