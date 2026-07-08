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


# ---------------------------------------------------------------------------
# get_variation_delivery_counts
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetVariationDeliveryCounts:
    def _setup_delivery(self, tenant):
        """Create a variation, delivery day, station day, and one delivery."""
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
            quantity=2,
        )

        share = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=delivery_day,
            share_type_variation=variation,
        )
        share_delivery = ShareDeliveryFactory(
            share=share,
            delivery_station_day=station_day,
        )
        share_delivery.subscription = subscription
        share_delivery.save()

        return variation, delivery_day, station_day

    def test_day_level_counts(self, tenant):
        variation, delivery_day, _ = self._setup_delivery(tenant)
        share_type_id = variation.share_type_id

        result = ShareDeliveryService.get_variation_delivery_counts(
            share_type_id=share_type_id,
            year=2026,
            delivery_week=15,
        )

        assert len(result) == 1
        row = result[0]
        assert row["share_type_variation_id"] == variation.pk
        assert f"amount_day_{delivery_day.pk}" in row

    def test_tour_level_counts(self, tenant):
        variation, delivery_day, _ = self._setup_delivery(tenant)

        result = ShareDeliveryService.get_variation_delivery_counts(
            share_type_id=variation.share_type_id,
            year=2026,
            delivery_week=15,
            for_tours=True,
        )

        assert len(result) == 1
        row = result[0]
        assert f"amount_day_{delivery_day.pk}_tour_1" in row

    def test_station_level_counts(self, tenant):
        variation, delivery_day, station_day = self._setup_delivery(tenant)
        station_id = station_day.delivery_station_id

        result = ShareDeliveryService.get_variation_delivery_counts(
            share_type_id=variation.share_type_id,
            year=2026,
            delivery_week=15,
            for_stations=True,
        )

        assert len(result) == 1
        row = result[0]
        assert f"amount_day_{delivery_day.pk}_station_{station_id}" in row

    def test_empty_when_no_deliveries(self, tenant):
        variation = ShareTypeVariationFactory()

        result = ShareDeliveryService.get_variation_delivery_counts(
            share_type_id=variation.share_type_id,
            year=2026,
            delivery_week=99,
        )

        # Variations still returned, just with 0 counts
        for row in result:
            for key, val in row.items():
                if key.startswith("amount_day_"):
                    assert val == 0

    def test_import_mode_reads_external_demand(self, tenant):
        """Import-safety lock. For an external-CSV (import) tenant there are NO
        ``ShareDelivery`` rows — demand lives in ``ExternalShareDemand``. The
        counts must still flow through (via ``ShareDemandService``), so a future
        edit that reads ``ShareDelivery`` directly in
        ``get_variation_delivery_counts`` fails HERE instead of silently
        blanking the AmountShares grid for import tenants."""
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2)
        station_day = DeliveryStationDayFactory(
            delivery_day=delivery_day, tour_number=1
        )

        # Aggregated, member-less demand — and deliberately NO ShareDelivery /
        # Subscription (the state of a pure import tenant).
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
            result = ShareDeliveryService.get_variation_delivery_counts(
                share_type_id=variation.share_type_id,
                year=2026,
                delivery_week=15,
            )

        assert len(result) == 1
        row = result[0]
        assert row["share_type_variation_id"] == variation.pk
        # The imported quantity flows through — NOT zero, which is what a direct
        # ShareDelivery read would yield (there are no ShareDelivery rows).
        assert row[f"amount_day_{delivery_day.pk}"] == 7
