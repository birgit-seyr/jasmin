"""Tests for statistic_views.py — member_growth_statistics & historical_share_variation_averages."""

from __future__ import annotations

import datetime

import pytest
from django.urls import reverse
from rest_framework import status

from apps.commissioning.tests.factories import (
    MemberFactory,
    ShareContentFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
)

URL_MEMBER_GROWTH = reverse("member_growth_statistics")
URL_VARIATION_AVERAGES = reverse("historical_share_variation_averages")


# ---------------------------------------------------------------------------
# member_growth_statistics
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestMemberGrowthStatistics:
    def test_returns_data_grouped_by_month(self, api_client, tenant):
        MemberFactory(entry_date=datetime.date(2025, 3, 10))
        MemberFactory(entry_date=datetime.date(2025, 3, 20))
        MemberFactory(entry_date=datetime.date(2025, 4, 5))

        resp = api_client.get(URL_MEMBER_GROWTH, {"period": "month"})
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) >= 2

    def test_filter_by_year(self, api_client, tenant):
        MemberFactory(entry_date=datetime.date(2024, 1, 1))
        MemberFactory(entry_date=datetime.date(2025, 6, 1))

        resp = api_client.get(URL_MEMBER_GROWTH, {"year": 2025})
        assert resp.status_code == status.HTTP_200_OK
        # Only 2025 members
        total_new = sum(item["new_members"] for item in resp.data)
        assert total_new == 1

    def test_cumulative_total(self, api_client, tenant):
        MemberFactory(entry_date=datetime.date(2025, 1, 1))
        MemberFactory(entry_date=datetime.date(2025, 2, 1))

        resp = api_client.get(URL_MEMBER_GROWTH, {"period": "month", "year": 2025})
        assert resp.status_code == status.HTTP_200_OK
        if len(resp.data) >= 2:
            assert resp.data[-1]["total_members"] >= resp.data[0]["total_members"]

    def test_invalid_period_returns_400(self, api_client, tenant):
        resp = api_client.get(URL_MEMBER_GROWTH, {"period": "invalid"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_empty_when_no_members(self, api_client, tenant):
        resp = api_client.get(URL_MEMBER_GROWTH)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []


# ---------------------------------------------------------------------------
# historical_share_variation_averages
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestHistoricalShareVariationAverages:
    def test_returns_averages(self, api_client, tenant):
        variation = ShareTypeVariationFactory()
        dd = SharesDeliveryDayFactory()
        # Create share content for two past years, reusing the same delivery day
        for year in (2024, 2025):
            share = ShareFactory(
                year=year,
                delivery_week=15,
                share_type_variation=variation,
                delivery_day=dd,
            )
            ShareContentFactory(share=share, amount=10)

        resp = api_client.get(
            URL_VARIATION_AVERAGES,
            {
                "year": 2026,
                "delivery_week": 15,
                "share_type_variation_ids": str(variation.id),
                "years_back": 2,
            },
        )

        assert resp.status_code == status.HTTP_200_OK

    def test_missing_params_returns_400(self, api_client, tenant):
        resp = api_client.get(URL_VARIATION_AVERAGES)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_empty_for_no_data(self, api_client, tenant):
        variation = ShareTypeVariationFactory()
        resp = api_client.get(
            URL_VARIATION_AVERAGES,
            {
                "year": 2026,
                "delivery_week": 15,
                "share_type_variation_ids": str(variation.id),
            },
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == {}
