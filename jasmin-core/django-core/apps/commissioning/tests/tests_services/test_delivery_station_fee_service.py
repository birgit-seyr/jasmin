"""Station-fee billing: per-box / per-month / per-year owed-amount math and
the read-only endpoint."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.commissioning.models import DeliveryStationDay, ShareDelivery
from apps.commissioning.services.delivery_station_fee_service import (
    DeliveryStationFeeService,
)
from apps.commissioning.services.subscription_service import SubscriptionService
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    SharesDeliveryDayFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)
from apps.commissioning.tests.factories.members import PaymentCycleFactory

_FROM = datetime.date(2026, 7, 6)  # Monday, ISO week 28
_UNTIL = datetime.date(2026, 8, 2)  # Sunday, ISO week 31 (4 Wednesday deliveries)


def _variation():
    return ShareTypeVariationFactory(
        share_type=ShareTypeFactory(share_option="HARVEST_SHARE")
    )


def _station_with_deliveries(*, quantity=1, **fees):
    """A station carrying the given fee(s) with a confirmed subscription that
    delivers on the 4 Wednesdays of weeks 28-31 to it (``quantity`` boxes
    each week)."""
    station = DeliveryStationFactory(**fees)
    variation = _variation()
    delivery_day = SharesDeliveryDayFactory(day_number=2)  # Wednesday
    dsd = DeliveryStationDayFactory(delivery_station=station, delivery_day=delivery_day)
    subscription = SubscriptionFactory(
        share_type_variation=variation,
        default_delivery_station_day=dsd,
        valid_from=_FROM,
        valid_until=_UNTIL,
        quantity=quantity,
        payment_cycle=PaymentCycleFactory(),
    )
    SubscriptionService().materialize_confirmed_subscription(subscription)
    return station, subscription


@pytest.mark.django_db
class TestComputeFeesBilling:
    def test_per_box_counts_delivered_boxes(self, tenant):
        station, _ = _station_with_deliveries(fee_per_box_net=Decimal("2.50"))

        result = DeliveryStationFeeService.compute_fees(station, _FROM, _UNTIL)

        assert result["fee_type"] == "per_box"
        assert result["quantity"] == 4  # four Wednesday deliveries in range
        assert result["quantity_unit"] == "boxes"
        assert result["rate_net"] == "2.50"
        assert result["total_net"] == "10.00"
        assert sum(line["boxes"] for line in result["lines"]) == 4

    def test_per_box_weights_by_subscription_quantity(self, tenant):
        # A quantity=2 subscription materialises ONE ShareDelivery per week but
        # 2 boxes physically pass through the station — the fee must count 8
        # (4 weeks × 2), not 4 rows.
        station, _ = _station_with_deliveries(
            quantity=2, fee_per_box_net=Decimal("2.50")
        )

        result = DeliveryStationFeeService.compute_fees(station, _FROM, _UNTIL)

        assert result["quantity"] == 8
        assert result["total_net"] == "20.00"

    def test_per_box_excludes_joker_and_out_of_range(self, tenant):
        station, subscription = _station_with_deliveries(
            fee_per_box_net=Decimal("2.00")
        )
        # Skip one week via a joker → it must not count as a delivered box.
        first = (
            ShareDelivery.objects.filter(subscription=subscription)
            .select_related("share")
            .order_by("share__delivery_week")
            .first()
        )
        first.joker_taken = True
        first.save(update_fields=["joker_taken"])

        # Narrow the range so only weeks 29-31 (3 deliveries) fall inside it, then
        # the joker on week 28 is moot; count the narrowed window instead.
        result = DeliveryStationFeeService.compute_fees(
            station, datetime.date(2026, 7, 13), _UNTIL
        )
        assert result["quantity"] == 3
        assert result["total_net"] == "6.00"

        # Full range with the joker on week 28 → 3 delivered boxes (joker skipped).
        full = DeliveryStationFeeService.compute_fees(station, _FROM, _UNTIL)
        assert full["quantity"] == 3

    def test_per_box_excludes_additional_shares(self, tenant):
        # Only STANDALONE (non-additional) boxes drive the per-box fee — the same
        # shares that consume station capacity. An ADDITIONAL (packed-along)
        # honey share delivered to the SAME station-day rides in another box, so
        # it takes no slot and must NOT be billed.
        station, _ = _station_with_deliveries(fee_per_box_net=Decimal("2.00"))
        dsd = DeliveryStationDay.objects.get(delivery_station=station)

        honey_sub = SubscriptionFactory(
            share_type_variation=ShareTypeVariationFactory(
                share_type=ShareTypeFactory(
                    share_option="HONEY_SHARE", is_additional_share_type=True
                )
            ),
            default_delivery_station_day=dsd,
            valid_from=_FROM,
            valid_until=_UNTIL,
            quantity=1,
            payment_cycle=PaymentCycleFactory(),
        )
        SubscriptionService().materialize_confirmed_subscription(honey_sub)

        # Sanity: the honey sub DID materialise deliveries to this station-day,
        # so a naive count would have wrongly included them.
        assert ShareDelivery.objects.filter(subscription=honey_sub).exists()

        result = DeliveryStationFeeService.compute_fees(station, _FROM, _UNTIL)

        # Still 4 (the harvest Wednesdays only) — the honey boxes are excluded.
        assert result["quantity"] == 4
        assert result["total_net"] == "8.00"

    def test_per_month_counts_calendar_months(self, tenant):
        station = DeliveryStationFactory(fee_per_month_net=Decimal("50.00"))
        # 2026-07-06 .. 2026-08-02 overlaps July + August = 2 calendar months.
        result = DeliveryStationFeeService.compute_fees(station, _FROM, _UNTIL)
        assert result["fee_type"] == "per_month"
        assert result["quantity"] == 2
        assert result["total_net"] == "100.00"
        assert result["lines"] == []

    def test_per_year_counts_calendar_years(self, tenant):
        station = DeliveryStationFactory(fee_per_year_net=Decimal("300.00"))
        result = DeliveryStationFeeService.compute_fees(station, _FROM, _UNTIL)
        assert result["fee_type"] == "per_year"
        assert result["quantity"] == 1
        assert result["total_net"] == "300.00"

    def test_compute_all_only_includes_fee_stations(self, tenant):
        with_fee = DeliveryStationFactory(fee_per_box_net=Decimal("1.00"))
        DeliveryStationFactory()  # no fee → excluded

        rows = DeliveryStationFeeService.compute_all(_FROM, _UNTIL)
        assert [r["delivery_station"] for r in rows] == [with_fee.id]


@pytest.mark.django_db
class TestBillingEndpoint:
    URL = reverse("delivery_station_fees")

    def test_returns_fees_for_fee_station(self, api_client, tenant):
        station, _ = _station_with_deliveries(fee_per_box_net=Decimal("2.50"))

        response = api_client.get(
            self.URL, {"start_date": "2026-07-06", "end_date": "2026-08-02"}
        )
        assert response.status_code == 200
        rows = response.json()
        row = next(r for r in rows if r["delivery_station"] == station.id)
        assert row["fee_type"] == "per_box"
        assert row["quantity"] == 4
        assert row["total_net"] == "10.00"

    def test_rejects_inverted_range(self, api_client, tenant):
        response = api_client.get(
            self.URL, {"start_date": "2026-08-02", "end_date": "2026-07-06"}
        )
        assert response.status_code == 400
