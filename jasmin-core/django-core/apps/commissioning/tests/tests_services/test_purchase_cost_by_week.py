"""Tests for ``ShareContentService.purchase_cost_by_week`` and the
``purchase_cost_by_week`` statistics endpoint.

The per-variation demand machinery (``variation_totals_by_week`` →
``ShareDemandService``) is covered by the planning-list tests, so it is patched
here with a controlled demand map — these tests target the new glue: the
``price_per_unit × amount × demand`` money aggregation, the ``is_purchased``
filter, per-ISO-week bucketing, and the emit-every-week-in-range behaviour.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.commissioning.services.share_content_service import ShareContentService
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    ShareArticleFactory,
    ShareContentFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
)

# ISO week 15 of 2026 spans Mon 2026-04-06 … Sun 2026-04-12; week 16 the week
# after. Fixed dates keep the ISO-week math deterministic.
WEEK_15_MONDAY = date(2026, 4, 6)
WEEK_15_SUNDAY = date(2026, 4, 12)
WEEK_16_SUNDAY = date(2026, 4, 19)

_TOTALS_PATH = (
    "apps.commissioning.services.share_content_service."
    "ShareContentService.variation_totals_by_week"
)

URL = "/api/commissioning/purchase_cost_by_week/"


def _make_purchased_content(
    *,
    amount: Decimal,
    price: Decimal,
    year: int = 2026,
    week: int = 15,
    is_purchased: bool = True,
):
    """A station-scoped ShareContent plus the ``(year, week)`` and station
    demand-lookup keys ``_total_quantity_for`` will resolve it under."""
    variation = ShareTypeVariationFactory()
    delivery_day = SharesDeliveryDayFactory(day_number=2)
    station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
    share = ShareFactory(
        year=year,
        delivery_week=week,
        delivery_day=delivery_day,
        share_type_variation=variation,
    )
    ShareContentFactory(
        share=share,
        share_article=ShareArticleFactory(is_purchased=is_purchased),
        delivery_station=station_day.delivery_station,
        amount=amount,
        price_per_unit=price,
        unit="KG",
        size="M",
    )
    station_key = (delivery_day.id, variation.id, station_day.delivery_station_id)
    return (year, week), station_key


@pytest.mark.django_db
class TestPurchaseCostByWeekService:
    def test_sums_price_times_amount_times_demand(self, tenant):
        week_key, station_key = _make_purchased_content(
            amount=Decimal("5.000"), price=Decimal("2.00")
        )
        demand = {week_key: {"station": {station_key: 3}}}
        with patch(_TOTALS_PATH, return_value=demand):
            result = ShareContentService().purchase_cost_by_week(
                WEEK_15_MONDAY, WEEK_15_SUNDAY
            )
        # 2.00 €/unit × 5.000 units/share × 3 shares = 30.00 €, money as string.
        assert result == [{"year": 2026, "week": 15, "amount": "30.00"}]

    def test_excludes_non_purchased_articles(self, tenant):
        week_key, station_key = _make_purchased_content(
            amount=Decimal("5.000"), price=Decimal("2.00"), is_purchased=False
        )
        demand = {week_key: {"station": {station_key: 3}}}
        with patch(_TOTALS_PATH, return_value=demand):
            result = ShareContentService().purchase_cost_by_week(
                WEEK_15_MONDAY, WEEK_15_SUNDAY
            )
        # A self-grown (not is_purchased) article is never a buy-in.
        assert result == [{"year": 2026, "week": 15, "amount": "0.00"}]

    def test_emits_zero_for_weeks_without_purchases(self, tenant):
        week_key, station_key = _make_purchased_content(
            amount=Decimal("4.000"), price=Decimal("1.50")
        )
        demand = {week_key: {"station": {station_key: 2}}}
        with patch(_TOTALS_PATH, return_value=demand):
            result = ShareContentService().purchase_cost_by_week(
                WEEK_15_MONDAY, WEEK_16_SUNDAY
            )
        # Every week in range is emitted chronologically; week 16 had no buy-ins.
        assert result == [
            {"year": 2026, "week": 15, "amount": "12.00"},  # 1.50 × 4.000 × 2
            {"year": 2026, "week": 16, "amount": "0.00"},
        ]

    def test_zero_demand_contributes_nothing(self, tenant):
        _make_purchased_content(amount=Decimal("5.000"), price=Decimal("2.00"))
        # No demand entry for the row → treated as 0 shares.
        with patch(_TOTALS_PATH, return_value={}):
            result = ShareContentService().purchase_cost_by_week(
                WEEK_15_MONDAY, WEEK_15_SUNDAY
            )
        assert result == [{"year": 2026, "week": 15, "amount": "0.00"}]


@pytest.mark.django_db
class TestPurchaseCostByWeekEndpoint:
    def test_requires_date_params(self, api_client):
        assert api_client.get(URL).status_code == 400

    def test_rejects_reversed_range(self, api_client):
        response = api_client.get(
            URL, {"start_date": "2026-04-12", "end_date": "2026-04-06"}
        )
        assert response.status_code == 400

    def test_returns_weekly_points(self, api_client):
        week_key, station_key = _make_purchased_content(
            amount=Decimal("5.000"), price=Decimal("2.00")
        )
        demand = {week_key: {"station": {station_key: 3}}}
        with patch(_TOTALS_PATH, return_value=demand):
            response = api_client.get(
                URL, {"start_date": "2026-04-06", "end_date": "2026-04-12"}
            )
        assert response.status_code == 200
        assert response.json() == [{"year": 2026, "week": 15, "amount": "30.00"}]

    def test_requires_authentication(self, anon_client):
        response = anon_client.get(
            URL, {"start_date": "2026-04-06", "end_date": "2026-04-12"}
        )
        # Office-only endpoint — an unauthenticated caller is rejected.
        assert response.status_code in (401, 403)
