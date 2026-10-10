"""``CHECK (tour_number >= 1) NOT VALID`` on the station-day table.

Tours start at 1. The check refuses every new or updated row below 1 and
leaves rows already stored alone, so it could be added while a tenant may
still hold a tour 0.
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, connection, transaction

from apps.commissioning.models import DeliveryStationDay
from apps.commissioning.tests.factories import DeliveryStationDayFactory
from apps.commissioning.tests.factories.days import (
    TOUR_NUMBER_CHECK,
    store_legacy_tour_number_zero,
)

TABLE = DeliveryStationDay._meta.db_table


@pytest.mark.django_db
class TestTourNumberCheck:
    def test_is_installed_not_validated(self, tenant):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT convalidated FROM pg_constraint "
                "WHERE conname = %s AND conrelid = %s::regclass",
                [TOUR_NUMBER_CHECK, TABLE],
            )
            rows = cursor.fetchall()

        assert rows == [(False,)]

    def test_refuses_creating_tour_zero(self, tenant):
        with pytest.raises(IntegrityError, match=TOUR_NUMBER_CHECK):
            with transaction.atomic():
                DeliveryStationDayFactory(tour_number=0)

    def test_refuses_setting_tour_zero_with_raw_sql(self, tenant):
        station_day = DeliveryStationDayFactory(tour_number=2)

        with pytest.raises(IntegrityError, match=TOUR_NUMBER_CHECK):
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {TABLE} SET tour_number = 0 WHERE id = %s",
                    [station_day.pk],
                )

        station_day.refresh_from_db()
        assert station_day.tour_number == 2

    def test_tour_one_is_allowed(self, tenant):
        station_day = DeliveryStationDayFactory(tour_number=1)

        assert DeliveryStationDay.objects.get(pk=station_day.pk).tour_number == 1


@pytest.mark.django_db
class TestLegacyTourZeroRow:
    """A row stored with tour 0 before the check stays readable; any UPDATE
    re-checks the whole row, so only one that names a tour of 1 or more
    goes through."""

    def test_stays_readable(self, tenant):
        station_day = DeliveryStationDayFactory()

        store_legacy_tour_number_zero(station_day)

        assert DeliveryStationDay.objects.get(pk=station_day.pk).tour_number == 0

    def test_an_update_of_another_column_is_refused(self, tenant):
        station_day = DeliveryStationDayFactory(capacity=50)
        store_legacy_tour_number_zero(station_day)

        with pytest.raises(IntegrityError, match=TOUR_NUMBER_CHECK):
            with transaction.atomic():
                DeliveryStationDay.objects.filter(pk=station_day.pk).update(capacity=40)

    def test_an_update_naming_a_tour_goes_through(self, tenant):
        station_day = DeliveryStationDayFactory()
        store_legacy_tour_number_zero(station_day)

        DeliveryStationDay.objects.filter(pk=station_day.pk).update(tour_number=2)

        assert DeliveryStationDay.objects.get(pk=station_day.pk).tour_number == 2
