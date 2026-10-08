"""Station-fee billing: per-box / per-month / per-year owed-amount math and
the read-only endpoint."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
import time_machine
from django.urls import reverse

from apps.commissioning.models import (
    DeliveryStationDay,
    ExternalShareDemand,
    ShareDelivery,
    ShareImportBatch,
)
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


def _enable_import_mode():
    """Flip the current tenant to external-CSV (import) demand so
    ``_resolve_backend`` picks the ExternalDemandBackend."""
    from django.db import connection
    from django.utils import timezone

    from apps.shared.tenants.models import Tenant, TenantSettings

    real = Tenant.objects.get(schema_name=connection.schema_name)
    current = TenantSettings.get_current_settings(real)
    if current:
        current.uploads_weekly_share_amount = True
        current.save(update_fields=["uploads_weekly_share_amount"])
    else:
        TenantSettings.objects.create(
            tenant=real,
            valid_from=timezone.now() - datetime.timedelta(days=1),
            uploads_weekly_share_amount=True,
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


@pytest.fixture(autouse=True)
def _freeze_clock():
    # The fixed fixture dates would count as past weeks, which the
    # materialisation/capacity past-week clamp skips; freeze "now" to that week so
    # the clamp is a no-op here.
    with time_machine.travel(datetime.date(2026, 7, 6), tick=False):
        yield


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

    def test_per_month_prorates_the_months_by_day(self, tenant):
        station = DeliveryStationFactory(fee_per_month_net=Decimal("50.00"))
        # 2026-07-06 .. 2026-08-02: 26 of July's 31 days and 2 of August's 31.
        result = DeliveryStationFeeService.compute_fees(station, _FROM, _UNTIL)
        assert result["fee_type"] == "per_month"
        assert result["billed_quantity"] == Decimal("0.9032")  # 28/31
        assert result["quantity"] == 1
        assert result["total_net"] == "45.16"  # 50 × 28/31 = 45.161…
        assert result["lines"] == []

    def test_per_year_prorates_the_year_by_day(self, tenant):
        station = DeliveryStationFactory(fee_per_year_net=Decimal("300.00"))
        result = DeliveryStationFeeService.compute_fees(station, _FROM, _UNTIL)
        assert result["fee_type"] == "per_year"
        assert result["billed_quantity"] == Decimal("0.0767")  # 28/365
        assert result["quantity"] == 1
        assert result["total_net"] == "23.01"  # 300 × 28/365 = 23.013…

    def test_per_box_bills_the_box_count(self, tenant):
        station, _ = _station_with_deliveries(fee_per_box_net=Decimal("2.50"))
        result = DeliveryStationFeeService.compute_fees(station, _FROM, _UNTIL)
        assert result["billed_quantity"] == Decimal("4")

    def test_compute_all_only_includes_fee_stations(self, tenant):
        with_fee = DeliveryStationFactory(fee_per_box_net=Decimal("1.00"))
        DeliveryStationFactory()  # no fee → excluded

        rows = DeliveryStationFeeService.compute_all(_FROM, _UNTIL)
        assert [r["delivery_station"] for r in rows] == [with_fee.id]


def _monthly(rate: str):
    return DeliveryStationFactory(fee_per_month_net=Decimal(rate))


def _yearly(rate: str):
    return DeliveryStationFactory(fee_per_year_net=Decimal(rate))


def _week(year: int, week: int) -> tuple[datetime.date, datetime.date]:
    monday = datetime.date.fromisocalendar(year, week, 1)
    return monday, monday + datetime.timedelta(days=6)


def _weeks_covering(year: int) -> list[tuple[datetime.date, datetime.date]]:
    """The calendar year cut into disjoint Monday-to-Sunday ranges, the first
    and last clipped to the year."""
    first, last = datetime.date(year, 1, 1), datetime.date(year, 12, 31)
    ranges = []
    start = first
    while start <= last:
        sunday = start + datetime.timedelta(days=6 - start.weekday())
        ranges.append((start, min(sunday, last)))
        start = sunday + datetime.timedelta(days=1)
    return ranges


@pytest.mark.django_db
class TestComputeFeesProration:
    """A monthly fee bills each month a range touches by the share of that
    month's days the range covers, a yearly fee each calendar year by the
    share of its days; the total is rounded to the cent once."""

    def test_week_41_bills_seven_days_of_october(self, tenant):
        start, end = _week(2026, 41)  # Mon 5 – Sun 11 October

        result = DeliveryStationFeeService.compute_fees(_monthly("31.00"), start, end)

        assert result["billed_quantity"] == Decimal("0.2258")  # 7/31
        assert result["quantity"] == 1
        assert result["quantity_unit"] == "months"
        assert result["total_net"] == "7.00"

    def test_week_1_of_2026_bills_the_days_of_both_months(self, tenant):
        start, end = _week(2026, 1)  # Mon 29 Dec 2025 – Sun 4 Jan 2026

        result = DeliveryStationFeeService.compute_fees(_monthly("31.00"), start, end)

        # 3/31 of December and 4/31 of January — not two whole months.
        assert result["billed_quantity"] == Decimal("0.2258")
        assert result["quantity"] == 1
        assert result["total_net"] == "7.00"

    def test_week_1_of_2026_bills_the_days_of_both_years(self, tenant):
        start, end = _week(2026, 1)

        result = DeliveryStationFeeService.compute_fees(_yearly("365.00"), start, end)

        # 3/365 of 2025 and 4/365 of 2026 — not two whole years.
        assert result["billed_quantity"] == Decimal("0.0192")
        assert result["quantity"] == 1
        assert result["quantity_unit"] == "years"
        assert result["total_net"] == "7.00"

    def test_a_full_year_bills_twelve_months(self, tenant):
        result = DeliveryStationFeeService.compute_fees(
            _monthly("35.00"), datetime.date(2026, 1, 1), datetime.date(2026, 12, 31)
        )

        assert result["billed_quantity"] == Decimal("12")
        assert result["quantity"] == 12
        assert result["total_net"] == "420.00"

    def test_a_full_year_bills_one_year(self, tenant):
        result = DeliveryStationFeeService.compute_fees(
            _yearly("120.00"), datetime.date(2026, 1, 1), datetime.date(2026, 12, 31)
        )

        assert result["billed_quantity"] == Decimal("1")
        assert result["quantity"] == 1
        assert result["total_net"] == "120.00"

    @pytest.mark.parametrize(
        ("station_factory", "rate", "yearly_total"),
        [
            (_monthly, "35.00", Decimal("420.00")),
            (_yearly, "100.00", Decimal("100.00")),
        ],
    )
    def test_disjoint_weeks_add_up_to_the_year(
        self, tenant, station_factory, rate, yearly_total
    ):
        station = station_factory(rate)
        ranges = _weeks_covering(2026)

        totals = [
            Decimal(
                DeliveryStationFeeService.compute_fees(station, start, end)["total_net"]
            )
            for start, end in ranges
        ]

        # Each range is rounded to the cent on its own, so the sum may drift by
        # at most half a cent per range.
        assert abs(sum(totals) - yearly_total) <= Decimal("0.005") * len(ranges)
        assert len(ranges) == 53

    def test_a_leap_year_counts_its_366_days(self, tenant):
        # February 2028 has 29 days, the year 366.
        result = DeliveryStationFeeService.compute_fees(
            _yearly("366.00"), datetime.date(2028, 2, 1), datetime.date(2028, 2, 29)
        )
        assert result["total_net"] == "29.00"

        whole = DeliveryStationFeeService.compute_fees(
            _yearly("366.00"), datetime.date(2028, 1, 1), datetime.date(2028, 12, 31)
        )
        assert whole["billed_quantity"] == Decimal("1")
        assert whole["total_net"] == "366.00"

    def test_a_leap_february_bills_by_its_29_days(self, tenant):
        result = DeliveryStationFeeService.compute_fees(
            _monthly("29.00"), datetime.date(2028, 2, 1), datetime.date(2028, 2, 14)
        )
        assert result["billed_quantity"] == Decimal("0.4828")  # 14/29
        assert result["total_net"] == "14.00"

    def test_a_mid_month_range_bills_its_days(self, tenant):
        # 10 – 24 September: 15 of September's 30 days.
        result = DeliveryStationFeeService.compute_fees(
            _monthly("40.00"), datetime.date(2026, 9, 10), datetime.date(2026, 9, 24)
        )
        assert result["billed_quantity"] == Decimal("0.5")
        assert result["quantity"] == 1
        assert result["total_net"] == "20.00"

    def test_the_total_is_rounded_once_not_per_month(self, tenant):
        # 0.06 a month over 3 December and 4 January days: 0.0058 + 0.0077
        # would round to 0.01 each, but the whole 0.06 × 7/31 = 0.0135 is 0.01.
        result = DeliveryStationFeeService.compute_fees(
            _monthly("0.06"), datetime.date(2025, 12, 29), datetime.date(2026, 1, 4)
        )
        assert result["total_net"] == "0.01"


@pytest.mark.django_db
class TestComputeFeesImportMode:
    """Import-safety lock: a fee station on the external-CSV import has ZERO
    ShareDelivery rows — the per-box fee must count boxes from
    ExternalShareDemand instead of silently billing 0."""

    def test_per_box_uses_external_demand(self, tenant):
        _enable_import_mode()
        station = DeliveryStationFactory(fee_per_box_net=Decimal("2.50"))
        variation = _variation()
        delivery_day = SharesDeliveryDayFactory(day_number=2)  # Wednesday
        dsd = DeliveryStationDayFactory(
            delivery_station=station, delivery_day=delivery_day
        )
        batch = ShareImportBatch.objects.create(
            year=2026,
            delivery_week=28,
            file_checksum="0" * 64,
            original_filename="seed.csv",
            status=ShareImportBatch.STATUS_APPLIED,
        )
        # One imported box per Wednesday of weeks 28-31 — and NO ShareDelivery.
        for week in (28, 29, 30, 31):
            ExternalShareDemand.objects.create(
                batch=batch,
                year=2026,
                delivery_week=week,
                delivery_station_day=dsd,
                share_type_variation=variation,
                quantity=1,
            )
        assert not ShareDelivery.objects.exists()

        result = DeliveryStationFeeService.compute_fees(station, _FROM, _UNTIL)

        assert result["fee_type"] == "per_box"
        # 4 Wednesdays, sourced from ExternalShareDemand — NOT 0 (which a direct
        # ShareDelivery read would yield here).
        assert result["quantity"] == 4
        assert result["total_net"] == "10.00"
        assert sum(line["boxes"] for line in result["lines"]) == 4

    def test_per_box_weights_by_imported_quantity(self, tenant):
        _enable_import_mode()
        station = DeliveryStationFactory(fee_per_box_net=Decimal("2.50"))
        variation = _variation()
        delivery_day = SharesDeliveryDayFactory(day_number=2)
        dsd = DeliveryStationDayFactory(
            delivery_station=station, delivery_day=delivery_day
        )
        batch = ShareImportBatch.objects.create(
            year=2026,
            delivery_week=28,
            file_checksum="0" * 64,
            original_filename="seed.csv",
            status=ShareImportBatch.STATUS_APPLIED,
        )
        for week in (28, 29, 30, 31):
            ExternalShareDemand.objects.create(
                batch=batch,
                year=2026,
                delivery_week=week,
                delivery_station_day=dsd,
                share_type_variation=variation,
                quantity=2,  # 2 boxes per week
            )

        result = DeliveryStationFeeService.compute_fees(station, _FROM, _UNTIL)

        assert result["quantity"] == 8  # 4 weeks × 2
        assert result["total_net"] == "20.00"


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
        assert row["billed_quantity"] == "4.0000"
        assert row["total_net"] == "10.00"

    def test_sends_the_prorated_quantity_as_a_string(self, api_client, tenant):
        station = DeliveryStationFactory(fee_per_month_net=Decimal("31.00"))

        response = api_client.get(
            self.URL, {"start_date": "2026-10-05", "end_date": "2026-10-11"}
        )

        assert response.status_code == 200
        row = next(r for r in response.json() if r["delivery_station"] == station.id)
        assert row["fee_type"] == "per_month"
        assert row["quantity"] == 1
        assert row["billed_quantity"] == "0.2258"
        assert row["total_net"] == "7.00"

    def test_rejects_inverted_range(self, api_client, tenant):
        response = api_client.get(
            self.URL, {"start_date": "2026-08-02", "end_date": "2026-07-06"}
        )
        assert response.status_code == 400
        # One code for an inverted range, whichever endpoint takes the pair.
        assert response.json()["code"] == "query.invalid_param"
        assert response.json()["field"] == "start_date"
