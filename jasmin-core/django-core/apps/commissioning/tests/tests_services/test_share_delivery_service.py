"""Tests for ShareDeliveryService."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.commissioning.models import (
    ExternalShareDemand,
    ShareDelivery,
    ShareImportBatch,
)
from apps.commissioning.services.share_delivery_service import ShareDeliveryService
from apps.commissioning.services.share_demand_service import ExternalDemandBackend
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    MemberFactory,
    PaymentCycleFactory,
    ShareDeliveryFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)


@pytest.mark.django_db
class TestGetWeeklyVariationCountMatrix:
    """The import (flat per-variation) AmountShares matrix: one ROW per delivery
    day (or day × tour / day × station), COLUMNS one per variation (empty
    ``add_ons``, ``variation_<id>`` keys), cell = count of that variation."""

    def _setup(self, tenant, quantity=2):
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2)
        station_day = DeliveryStationDayFactory(
            delivery_day=delivery_day, tour_number=1
        )
        member = MemberFactory()
        payment_cycle = PaymentCycleFactory()
        subscription = SubscriptionFactory(
            member=member,
            share_type_variation=variation,
            payment_cycle=payment_cycle,
            default_delivery_station_day=station_day,
            quantity=quantity,
        )
        share = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=variation,
        )
        share_delivery = ShareDeliveryFactory(
            share=share, delivery_station_day=station_day
        )
        share_delivery.subscription = subscription
        share_delivery.save()
        return variation, delivery_day, station_day

    def test_days_as_rows_flat_variation_columns(self, tenant):
        variation, delivery_day, _station = self._setup(tenant, quantity=2)

        result = ShareDeliveryService.get_weekly_variation_count_matrix(
            year=2026, delivery_week=15, mode="day"
        )

        # One FLAT column for the variation (empty add_ons), keyed variation_<id>.
        assert len(result["columns"]) == 1
        column = result["columns"][0]
        assert column["base_variation_id"] == variation.pk
        assert column["add_ons"] == []
        column_key = column["key"]
        assert column_key == f"variation_{variation.pk}"

        # One row for the delivery day, carrying the variation's count.
        assert len(result["rows"]) == 1
        row = result["rows"][0]
        assert row["id"] == str(delivery_day.pk)
        assert row["day_number"] == 2
        assert row["tour"] is None
        assert row["delivery_station_id"] is None
        assert row[column_key] == 2

    def test_stations_mode_row_carries_station(self, tenant):
        variation, delivery_day, station_day = self._setup(tenant, quantity=1)

        result = ShareDeliveryService.get_weekly_variation_count_matrix(
            year=2026, delivery_week=15, mode="stations"
        )

        column_key = result["columns"][0]["key"]
        assert len(result["rows"]) == 1
        row = result["rows"][0]
        assert row["delivery_station_id"] == station_day.delivery_station_id
        assert row["id"] == (
            f"{delivery_day.pk}_station_{station_day.delivery_station_id}"
        )
        assert row[column_key] == 1

    def test_import_tenant_reads_external_demand(self, tenant):
        """Import-safety lock for the AmountShareTypeVariations matrix: on an
        external-CSV (import) tenant there are NO ``ShareDelivery`` rows — demand
        lives in ``ExternalShareDemand`` and must surface as the directly-imported
        quantity in the flat per-variation column. This is exactly what the
        ``box_combination_matrix`` endpoint's import branch returns for that page,
        so a future edit that reads ``ShareDelivery`` directly fails HERE."""
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2)
        station_day = DeliveryStationDayFactory(
            delivery_day=delivery_day, tour_number=1
        )
        batch = ShareImportBatch.objects.create(
            year=2026,
            delivery_week=15,
            file_checksum="0" * 64,
            original_filename="seed.csv",
            status=ShareImportBatch.STATUS_APPLIED,
        )
        ExternalShareDemand.objects.create(
            batch=batch,
            year=2026,
            delivery_week=15,
            delivery_station_day=station_day,
            share_type_variation=variation,
            quantity=7,
        )
        assert not ShareDelivery.objects.exists()

        with patch(
            "apps.commissioning.services.share_demand_service._resolve_backend",
            return_value=ExternalDemandBackend(),
        ):
            result = ShareDeliveryService.get_weekly_variation_count_matrix(
                year=2026, delivery_week=15, mode="day"
            )

        # One flat variation column, one day row, carrying the imported quantity
        # (7) — NOT zero, which a direct ShareDelivery read would yield.
        assert len(result["columns"]) == 1
        column_key = result["columns"][0]["key"]
        assert column_key == f"variation_{variation.pk}"
        assert len(result["rows"]) == 1
        assert result["rows"][0]["day_number"] == 2
        assert result["rows"][0][column_key] == 7
