"""Tests for documentation_views.py — DocumentationOverviewView."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status

from apps.commissioning.tests.factories import (
    HarvestFactory,
    PurchaseFactory,
    ShareArticleFactory,
    StorageFactory,
    WasteFactory,
)

URL = reverse("documentation_overview")


@pytest.mark.django_db
class TestDocumentationOverviewGet:
    def test_harvest_aggregation(self, api_client, tenant):
        article = ShareArticleFactory()
        extra_storage = StorageFactory(name="Aux Harvest Storage")
        HarvestFactory(
            share_article=article,
            year=2026,
            delivery_week=15,
            day_number=1,
            unit="KG",
            size="M",
            amount=Decimal("10"),
        )
        HarvestFactory(
            share_article=article,
            year=2026,
            delivery_week=15,
            day_number=1,
            unit="KG",
            size="M",
            amount=Decimal("20"),
            storage=extra_storage,
        )

        resp = api_client.get(
            URL,
            {
                "year": 2026,
                "delivery_week": 15,
                "share_article": str(article.id),
                "source": "HARVEST",
            },
        )

        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        # Decimal STRING on the wire (money/quantity rule) — the view
        # serializes through DocumentationAggregationItemSerializer.
        assert resp.data[0]["amount"] == "30.000"

    def test_purchase_aggregation(self, api_client, tenant):
        article = ShareArticleFactory(is_purchased=True)
        PurchaseFactory(
            share_article=article,
            year=2026,
            delivery_week=15,
            unit="KG",
            size="M",
            amount=Decimal("50"),
        )

        resp = api_client.get(
            URL,
            {
                "year": 2026,
                "delivery_week": 15,
                "share_article": str(article.id),
                "source": "PURCHASE",
            },
        )

        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        assert resp.data[0]["amount"] == "50.000"

    def test_waste_aggregation(self, api_client, tenant):
        article = ShareArticleFactory()
        WasteFactory(
            share_article=article,
            year=2026,
            delivery_week=15,
            day_number=1,
            unit="KG",
            size="M",
            amount=Decimal("5"),
        )

        resp = api_client.get(
            URL,
            {
                "year": 2026,
                "delivery_week": 15,
                "share_article": str(article.id),
                "source": "WASTE",
            },
        )

        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        assert resp.data[0]["amount"] == "5.000"

    def test_empty_when_no_data(self, api_client, tenant):
        article = ShareArticleFactory()
        resp = api_client.get(
            URL,
            {
                "year": 2026,
                "delivery_week": 15,
                "share_article": str(article.id),
                "source": "HARVEST",
            },
        )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []

    def test_filters_by_day(self, api_client, tenant):
        article = ShareArticleFactory()
        HarvestFactory(
            share_article=article,
            year=2026,
            delivery_week=15,
            day_number=1,
            unit="KG",
            size="M",
            amount=Decimal("10"),
        )
        HarvestFactory(
            share_article=article,
            year=2026,
            delivery_week=15,
            day_number=2,
            unit="KG",
            size="M",
            amount=Decimal("20"),
        )

        resp = api_client.get(
            URL,
            {
                "year": 2026,
                "delivery_week": 15,
                "day_number": 1,
                "share_article": str(article.id),
                "source": "HARVEST",
            },
        )

        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        assert resp.data[0]["amount"] == "10.000"

    def test_missing_share_article_returns_400(self, api_client, tenant):
        resp = api_client.get(
            URL,
            {"year": 2026, "source": "HARVEST"},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_source_returns_400(self, api_client, tenant):
        article = ShareArticleFactory()
        resp = api_client.get(
            URL,
            {
                "year": 2026,
                "share_article": str(article.id),
                "source": "INVALID",
            },
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_year_returns_400(self, api_client, tenant):
        article = ShareArticleFactory()
        resp = api_client.get(
            URL,
            {
                "share_article": str(article.id),
                "source": "HARVEST",
            },
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
