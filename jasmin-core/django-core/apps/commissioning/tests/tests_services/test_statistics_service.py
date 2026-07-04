"""Tests for statistics (historical share variation averages)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.commissioning.services.statistics import (
    calculate_historical_share_type_variation_averages,
)
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    ShareContentFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
)


# ---------------------------------------------------------------------------
# calculate_historical_share_type_variation_averages (multiple)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCalculateHistoricalAveragesMultiple:
    def test_combines_multiple_variations(self, tenant):
        v1 = ShareTypeVariationFactory()
        v2 = ShareTypeVariationFactory()

        result = calculate_historical_share_type_variation_averages(
            [v1.pk, v2.pk], 2026, 15
        )
        # With no data, should return empty
        assert result == {}

    def test_skips_nonexistent_variations(self, tenant):
        result = calculate_historical_share_type_variation_averages([999999], 2026, 15)
        assert result == {}


# ---------------------------------------------------------------------------
# Query-count regression lock
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestHistoricalAveragesQueryCount:
    """Adding variations must not add proportional queries: the whole batch is
    one ShareContent scan plus one tour lookup, not one scan (and a point
    lookup) per variation."""

    def _make_variation_with_content(self, delivery_day, dsd):
        variation = ShareTypeVariationFactory()
        share = ShareFactory(
            year=2025,
            delivery_week=10,
            delivery_day=delivery_day,
            share_type_variation=variation,
        )
        ShareContentFactory(
            share=share,
            delivery_station=dsd.delivery_station,
            amount=Decimal("5"),
            unit="KG",
            size="M",
        )
        return variation.pk

    def test_scan_is_batched_across_variations(self, tenant):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        delivery_day = SharesDeliveryDayFactory(day_number=2)
        dsd = DeliveryStationDayFactory(delivery_day=delivery_day, tour_number=1)

        few_ids = [
            self._make_variation_with_content(delivery_day, dsd) for _ in range(2)
        ]
        with CaptureQueriesContext(connection) as ctx_small:
            calculate_historical_share_type_variation_averages(few_ids, 2026, 15)
        small = len(ctx_small.captured_queries)

        many_ids = few_ids + [
            self._make_variation_with_content(delivery_day, dsd) for _ in range(6)
        ]
        with CaptureQueriesContext(connection) as ctx_large:
            calculate_historical_share_type_variation_averages(many_ids, 2026, 15)
        large = len(ctx_large.captured_queries)

        assert large - small <= 2, (
            f"historical averages N+1 suspected: 2 variations -> {small} queries, "
            f"8 variations -> {large} queries (delta {large - small})."
        )
