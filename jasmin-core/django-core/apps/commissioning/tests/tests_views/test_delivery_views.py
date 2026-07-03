"""Tests for delivery_views.py — DeliveryStationsToursOverviewView."""

from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import ShareDelivery
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    ShareDeliveryFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
)

URL = reverse("delivery_station_tours_overview")


@pytest.mark.django_db
class TestDeliveryStationsToursOverviewView:
    """Tests for GET /api/commissioning/delivery-stations-tours-overview/."""

    def test_missing_year_returns_400(self, api_client, tenant):
        resp = api_client.get(URL, {"delivery_week": 15, "day_number": 1})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_delivery_week_returns_400(self, api_client, tenant):
        resp = api_client.get(URL, {"year": 2026, "day_number": 1})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_day_number_returns_400(self, api_client, tenant):
        resp = api_client.get(URL, {"year": 2026, "delivery_week": 15})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_no_delivery_day_returns_404(self, api_client, tenant):
        """No SharesDeliveryDay for the given day_number → 404."""
        resp = api_client.get(URL, {"year": 2026, "delivery_week": 15, "day_number": 1})
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_returns_overview_with_tours(self, api_client, tenant):
        dd = SharesDeliveryDayFactory(day_number=1, number_of_tours=2)
        _variation = ShareTypeVariationFactory()
        _dsd = DeliveryStationDayFactory(delivery_day=dd, tour_number=1)

        resp = api_client.get(
            URL,
            {
                "year": dd.valid_from.isocalendar()[0],
                "delivery_week": dd.valid_from.isocalendar()[1],
                "day_number": 1,
            },
        )
        assert resp.status_code == status.HTTP_200_OK
        assert "tours" in resp.data
        assert "variations" in resp.data

    def test_response_contains_year_and_week(self, api_client, tenant):
        dd = SharesDeliveryDayFactory(day_number=2, number_of_tours=1)
        DeliveryStationDayFactory(delivery_day=dd, tour_number=1)

        resp = api_client.get(
            URL,
            {
                "year": dd.valid_from.isocalendar()[0],
                "delivery_week": dd.valid_from.isocalendar()[1],
                "day_number": 2,
            },
        )
        assert resp.status_code == status.HTTP_200_OK
        assert "year" in resp.data
        assert "delivery_week" in resp.data
        assert "day_number" in resp.data

    def test_invalid_year_returns_400(self, api_client, tenant):
        resp = api_client.get(
            URL, {"year": "abc", "delivery_week": 15, "day_number": 1}
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_demand_grid_is_batched_not_per_cell(self, api_client, tenant):
        """MT-4: the (station_day, variation) demand grid must come from ONE
        batched ShareDelivery aggregate, not a query per cell. Adding variations
        must NOT multiply the number of ShareDelivery queries (the old per-cell
        N+1 ran one aggregate per station_day × variation)."""
        table = ShareDelivery._meta.db_table
        dd = SharesDeliveryDayFactory(day_number=1, number_of_tours=1)
        year, week = dd.valid_from.isocalendar()[0], dd.valid_from.isocalendar()[1]
        station_days = [
            DeliveryStationDayFactory(delivery_day=dd, tour_number=1) for _ in range(2)
        ]

        def _add_active_variation():
            # A variation only appears in the grid once it has a real delivery.
            variation = ShareTypeVariationFactory()
            share = ShareFactory(
                year=year,
                delivery_week=week,
                share_type_variation=variation,
                delivery_day=dd,
            )
            ShareDeliveryFactory(
                share=share,
                delivery_station_day=station_days[0],
                joker_taken=False,
            )

        def _measure():
            with CaptureQueriesContext(connection) as ctx:
                resp = api_client.get(
                    URL, {"year": year, "delivery_week": week, "day_number": 1}
                )
                assert resp.status_code == status.HTTP_200_OK
            queries = sum(table in q["sql"] for q in ctx.captured_queries)
            return queries, len(resp.data["variations"])

        _add_active_variation()  # 1 active variation
        one_q, one_v = _measure()
        _add_active_variation()
        _add_active_variation()  # 3 active variations
        three_q, three_v = _measure()

        # Sanity: the variations really populate the grid (2 station_days each),
        # so the old per-cell N+1 WOULD manifest — otherwise this is a false pass.
        assert (one_v, three_v) == (1, 3)
        assert three_q - one_q <= 1, (
            f"demand queries scale with variations: 1 var -> {one_q} "
            f"ShareDelivery queries, 3 vars -> {three_q}. The grid must be "
            "one batched aggregate, not a per-cell query."
        )
