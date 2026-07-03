"""Tests for share_views.py — granularity, variation totals, planning amounts."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework import status

from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    ShareArticleFactory,
    ShareContentFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
)

URL_GRANULARITY = reverse("granularity")
URL_VARIATION_TOTALS = reverse("share_type_variations_totals")
URL_PLANNING = reverse("share_variation_amounts_for_planning")


# ---------------------------------------------------------------------------
# ShareContentGranularityView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestShareContentGranularityView:
    def test_empty_data_returns_ok(self, api_client, tenant):
        resp = api_client.get(URL_GRANULARITY, {"year": 2026, "delivery_week": 15})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["days_ok"] is True
        assert resp.data["tours_ok"] is True

    def test_missing_params_returns_400(self, api_client, tenant):
        resp = api_client.get(URL_GRANULARITY, {"year": 2026})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_consistent_data_returns_true(self, api_client, tenant):
        variation = ShareTypeVariationFactory()
        dd = SharesDeliveryDayFactory(day_number=1)
        share = ShareFactory(
            year=2026,
            delivery_week=15,
            share_type_variation=variation,
            delivery_day=dd,
        )
        ShareContentFactory(share=share, amount=10, unit="KG", size="M")

        resp = api_client.get(URL_GRANULARITY, {"year": 2026, "delivery_week": 15})
        assert resp.status_code == status.HTTP_200_OK

    def test_day_number_scopes_to_one_delivery_day(self, api_client, tenant):
        # day_number scopes the consistency check to a single delivery day: a day
        # whose stations agree reads days_ok=True even when ANOTHER delivery day
        # the same week diverges (which makes the global, unscoped check False).
        # The global result (no day_number) is kept for PlanningHarvestSharesBase.
        variation = ShareTypeVariationFactory()
        article = ShareArticleFactory()

        def _two_stations(delivery_day, amount_a, amount_b):
            # One Share per (delivery_day, variation) — unique — with two
            # ShareContents at different stations (the consistency axis).
            share = ShareFactory(
                year=2026,
                delivery_week=15,
                share_type_variation=variation,
                delivery_day=delivery_day,
            )
            for amount in (amount_a, amount_b):
                station = DeliveryStationDayFactory(delivery_day=delivery_day)
                ShareContentFactory(
                    share=share,
                    share_article=article,
                    delivery_station=station.delivery_station,
                    amount=amount,
                    unit="KG",
                    size="M",
                )

        # Delivery day 1: stations agree. Delivery day 2: stations diverge.
        _two_stations(SharesDeliveryDayFactory(day_number=1), 10, 10)
        _two_stations(SharesDeliveryDayFactory(day_number=2), 10, 3)

        base = {"year": 2026, "delivery_week": 15}
        # Global (no day_number): divergent day 2 makes it False.
        assert api_client.get(URL_GRANULARITY, base).data["days_ok"] is False
        # Scoped to the consistent day: True.
        assert (
            api_client.get(URL_GRANULARITY, {**base, "day_number": 1}).data["days_ok"]
            is True
        )
        # Scoped to the divergent day: False.
        assert (
            api_client.get(URL_GRANULARITY, {**base, "day_number": 2}).data["days_ok"]
            is False
        )


# ---------------------------------------------------------------------------
# ShareTypeVariationsTotalsView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestShareTypeVariationsTotalsView:
    def test_missing_delivery_day_returns_400(self, api_client, tenant):
        resp = api_client.get(URL_VARIATION_TOTALS, {"year": 2026, "delivery_week": 15})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_returns_variations(self, api_client, tenant):
        dd = SharesDeliveryDayFactory(day_number=1)

        resp = api_client.get(
            URL_VARIATION_TOTALS,
            {"year": 2026, "delivery_week": 15, "delivery_day": str(dd.id)},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert "variations" in resp.data

    def test_missing_year_returns_400(self, api_client, tenant):
        resp = api_client.get(
            URL_VARIATION_TOTALS, {"delivery_week": 15, "delivery_day": "x"}
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# ShareVariationAmountsForPlanningView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestShareVariationAmountsForPlanningView:
    def test_missing_share_option_returns_400(self, api_client, tenant):
        resp = api_client.get(URL_PLANNING, {"year": 2026, "delivery_week": 15})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_returns_planning_data(self, api_client, tenant):
        resp = api_client.get(
            URL_PLANNING,
            {
                "year": 2026,
                "delivery_week": 15,
                "share_option": "HARVEST_SHARE",
            },
        )
        assert resp.status_code == status.HTTP_200_OK
        # Bare object, matching the declared schema — the previous
        # one-element array wrapper was an audit finding (S3) and was
        # removed from the view.
        assert isinstance(resp.data, dict)

    def test_missing_year_returns_400(self, api_client, tenant):
        resp = api_client.get(
            URL_PLANNING,
            {"delivery_week": 15, "share_option": "HARVEST_SHARE"},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
