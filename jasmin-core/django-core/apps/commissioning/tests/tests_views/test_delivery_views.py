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
    MemberFactory,
    ShareDeliveryFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
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

    def test_each_tour_carries_own_columns_empty_tours_omitted(
        self, api_client, tenant
    ):
        """Each returned tour carries only the box combinations that occur on
        it (they differ across tours); a tour with no deliveries is omitted."""
        dd = SharesDeliveryDayFactory(day_number=1, number_of_tours=3)
        year, week = dd.valid_from.isocalendar()[0], dd.valid_from.isocalendar()[1]

        # Two base variations of one share type → two distinct combinations.
        var_m = ShareTypeVariationFactory(size="M")
        var_l = ShareTypeVariationFactory(size="L")

        station_day_1 = DeliveryStationDayFactory(delivery_day=dd, tour_number=1)
        station_day_2 = DeliveryStationDayFactory(delivery_day=dd, tour_number=2)
        # Tour 3 has a station but NO deliveries → must be omitted.
        DeliveryStationDayFactory(delivery_day=dd, tour_number=3)

        share_m = ShareFactory(
            year=year, delivery_week=week, delivery_day=dd, share_type_variation=var_m
        )
        share_l = ShareFactory(
            year=year, delivery_week=week, delivery_day=dd, share_type_variation=var_l
        )

        member_a = MemberFactory()
        sub_a = SubscriptionFactory(
            member=member_a,
            share_type_variation=var_m,
            quantity=1,
            default_delivery_station_day=station_day_1,
        )
        ShareDeliveryFactory(
            share=share_m, delivery_station_day=station_day_1, subscription=sub_a
        )

        member_b = MemberFactory()
        sub_b = SubscriptionFactory(
            member=member_b,
            share_type_variation=var_l,
            quantity=1,
            default_delivery_station_day=station_day_2,
        )
        ShareDeliveryFactory(
            share=share_l, delivery_station_day=station_day_2, subscription=sub_b
        )

        resp = api_client.get(
            URL, {"year": year, "delivery_week": week, "day_number": 1}
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data

        tours = resp.data["tours"]
        # Tour 3 (no deliveries) omitted; tours 1 and 2 remain.
        assert {tour["tour_number"] for tour in tours} == {1, 2}

        by_number = {tour["tour_number"]: tour for tour in tours}
        assert len(by_number[1]["columns"]) == 1
        assert len(by_number[2]["columns"]) == 1
        # Columns differ across tours (base-M on tour 1, base-L on tour 2).
        key_1 = by_number[1]["columns"][0]["key"]
        key_2 = by_number[2]["columns"][0]["key"]
        assert key_1 != key_2

        # The tour-1 station carries its combination's box count.
        station_1 = by_number[1]["stations"][0]
        assert station_1[key_1] == 1

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
