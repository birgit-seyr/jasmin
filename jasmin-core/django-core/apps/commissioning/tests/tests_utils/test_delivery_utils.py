"""Tests for apps.commissioning.utils.delivery_utils."""

from __future__ import annotations

import datetime

import pytest
from isoweek import Week
from rest_framework import status

from apps.commissioning.errors import SharesDeliveryDayNotFound
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    ShareDeliveryFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
)
from apps.commissioning.utils.delivery_utils import (
    get_active_share_type_variations,
    get_delivery_station_days_from_shares_delivery_day,
    get_shares_delivery_day_from_day_number,
)

YEAR = 2026
WEEK = 15
DAY_NUMBER = 2  # Wednesday


# ---------------------------------------------------------------------------
# get_shares_delivery_day_from_day_number
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetSharesDeliveryDayFromDayNumber:
    def test_returns_delivery_day_when_found(self, tenant):
        sdd = SharesDeliveryDayFactory(
            day_number=DAY_NUMBER,
            valid_from=datetime.date(2025, 12, 29),
        )

        result, active_date = get_shares_delivery_day_from_day_number(
            YEAR, WEEK, DAY_NUMBER
        )

        assert result is not None
        assert result.pk == sdd.pk

    def test_returns_correct_date(self, tenant):
        SharesDeliveryDayFactory(
            day_number=DAY_NUMBER,
            valid_from=datetime.date(2025, 12, 29),
        )

        _, active_date = get_shares_delivery_day_from_day_number(YEAR, WEEK, DAY_NUMBER)

        expected = Week(YEAR, WEEK).monday() + datetime.timedelta(days=DAY_NUMBER)
        assert active_date == expected

    def test_raises_not_found_when_missing(self, tenant):
        # No SharesDeliveryDay created for day_number=5
        with pytest.raises(SharesDeliveryDayNotFound) as excinfo:
            get_shares_delivery_day_from_day_number(YEAR, WEEK, 5)

        assert excinfo.value.http_status == status.HTTP_404_NOT_FOUND
        assert excinfo.value.code == "shares_delivery_day.not_found"

    def test_monday_day_number_zero(self, tenant):
        SharesDeliveryDayFactory(
            day_number=0,
            valid_from=datetime.date(2025, 12, 29),
        )

        result, active_date = get_shares_delivery_day_from_day_number(YEAR, WEEK, 0)

        assert result is not None
        expected = Week(YEAR, WEEK).monday()
        assert active_date == expected


# ---------------------------------------------------------------------------
# get_delivery_station_days_from_shares_delivery_day
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetDeliveryStationDaysFromSharesDeliveryDay:
    def test_returns_station_days_for_delivery_day(self, tenant):
        sdd = SharesDeliveryDayFactory(
            day_number=DAY_NUMBER,
            valid_from=datetime.date(2025, 12, 29),
        )
        dsd1 = DeliveryStationDayFactory(
            delivery_day=sdd,
            tour_number=1,
            stop_order=1,
            valid_from=datetime.date(2025, 12, 29),
        )
        dsd2 = DeliveryStationDayFactory(
            delivery_day=sdd,
            tour_number=1,
            stop_order=2,
            valid_from=datetime.date(2025, 12, 29),
        )

        active_date = Week(YEAR, WEEK).monday() + datetime.timedelta(days=DAY_NUMBER)
        result = get_delivery_station_days_from_shares_delivery_day(sdd, active_date)

        pks = list(result.values_list("pk", flat=True))
        assert dsd1.pk in pks
        assert dsd2.pk in pks

    def test_ordered_by_tour_and_stop(self, tenant):
        sdd = SharesDeliveryDayFactory(
            day_number=DAY_NUMBER,
            valid_from=datetime.date(2025, 12, 29),
        )
        dsd_second = DeliveryStationDayFactory(
            delivery_day=sdd,
            tour_number=2,
            stop_order=1,
            valid_from=datetime.date(2025, 12, 29),
        )
        dsd_first = DeliveryStationDayFactory(
            delivery_day=sdd,
            tour_number=1,
            stop_order=1,
            valid_from=datetime.date(2025, 12, 29),
        )

        active_date = Week(YEAR, WEEK).monday() + datetime.timedelta(days=DAY_NUMBER)
        result = list(
            get_delivery_station_days_from_shares_delivery_day(sdd, active_date)
        )

        assert result[0].pk == dsd_first.pk
        assert result[1].pk == dsd_second.pk

    def test_excludes_other_delivery_days(self, tenant):
        sdd = SharesDeliveryDayFactory(
            day_number=DAY_NUMBER,
            valid_from=datetime.date(2025, 12, 29),
        )
        other_sdd = SharesDeliveryDayFactory(
            day_number=4,
            valid_from=datetime.date(2025, 12, 29),
        )
        DeliveryStationDayFactory(
            delivery_day=sdd,
            tour_number=1,
            valid_from=datetime.date(2025, 12, 29),
        )
        dsd_other = DeliveryStationDayFactory(
            delivery_day=other_sdd,
            tour_number=1,
            valid_from=datetime.date(2025, 12, 29),
        )

        active_date = Week(YEAR, WEEK).monday() + datetime.timedelta(days=DAY_NUMBER)
        result = get_delivery_station_days_from_shares_delivery_day(sdd, active_date)

        pks = list(result.values_list("pk", flat=True))
        assert dsd_other.pk not in pks


# ---------------------------------------------------------------------------
# get_active_share_type_variations
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetActiveShareTypeVariations:
    def test_returns_variations_with_deliveries(self, tenant):
        sdd = SharesDeliveryDayFactory(
            day_number=DAY_NUMBER,
            valid_from=datetime.date(2025, 12, 29),
        )
        dsd = DeliveryStationDayFactory(
            delivery_day=sdd,
            tour_number=1,
            valid_from=datetime.date(2025, 12, 29),
        )
        variation = ShareTypeVariationFactory()
        share = ShareFactory(
            year=YEAR,
            delivery_week=WEEK,
            delivery_day=sdd,
            share_type_variation=variation,
        )
        ShareDeliveryFactory(
            share=share,
            delivery_station_day=dsd,
            joker_taken=False,
        )

        station_days = get_delivery_station_days_from_shares_delivery_day(
            sdd,
            Week(YEAR, WEEK).monday() + datetime.timedelta(days=DAY_NUMBER),
        )
        result = get_active_share_type_variations(YEAR, WEEK, sdd, station_days)

        assert variation.pk in list(result.values_list("pk", flat=True))

    def test_excludes_joker_deliveries(self, tenant):
        sdd = SharesDeliveryDayFactory(
            day_number=DAY_NUMBER,
            valid_from=datetime.date(2025, 12, 29),
        )
        dsd = DeliveryStationDayFactory(
            delivery_day=sdd,
            tour_number=1,
            valid_from=datetime.date(2025, 12, 29),
        )
        variation = ShareTypeVariationFactory()
        share = ShareFactory(
            year=YEAR,
            delivery_week=WEEK,
            delivery_day=sdd,
            share_type_variation=variation,
        )
        ShareDeliveryFactory(
            share=share,
            delivery_station_day=dsd,
            joker_taken=True,
        )

        station_days = get_delivery_station_days_from_shares_delivery_day(
            sdd,
            Week(YEAR, WEEK).monday() + datetime.timedelta(days=DAY_NUMBER),
        )
        result = get_active_share_type_variations(YEAR, WEEK, sdd, station_days)

        assert variation.pk not in list(result.values_list("pk", flat=True))

    def test_returns_distinct_variations(self, tenant):
        sdd = SharesDeliveryDayFactory(
            day_number=DAY_NUMBER,
            valid_from=datetime.date(2025, 12, 29),
        )
        dsd1 = DeliveryStationDayFactory(
            delivery_day=sdd,
            tour_number=1,
            valid_from=datetime.date(2025, 12, 29),
        )
        dsd2 = DeliveryStationDayFactory(
            delivery_day=sdd,
            tour_number=2,
            valid_from=datetime.date(2025, 12, 29),
        )
        variation = ShareTypeVariationFactory()
        # One share with two deliveries at different stations → same variation
        share = ShareFactory(
            year=YEAR,
            delivery_week=WEEK,
            delivery_day=sdd,
            share_type_variation=variation,
        )
        ShareDeliveryFactory(share=share, delivery_station_day=dsd1, joker_taken=False)
        ShareDeliveryFactory(share=share, delivery_station_day=dsd2, joker_taken=False)

        station_days = get_delivery_station_days_from_shares_delivery_day(
            sdd,
            Week(YEAR, WEEK).monday() + datetime.timedelta(days=DAY_NUMBER),
        )
        result = get_active_share_type_variations(YEAR, WEEK, sdd, station_days)

        # Should appear only once despite two deliveries
        pks = list(result.values_list("pk", flat=True))
        assert pks.count(variation.pk) == 1
