from __future__ import annotations

import datetime

import factory
from django.db import connection

from apps.commissioning.models import (
    DeliveryStationDay,
    OrdersDeliveryDay,
    SharesDeliveryDay,
)

from .delivery import DeliveryStationFactory


class SharesDeliveryDayFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SharesDeliveryDay

    day_number = 2  # Wednesday
    valid_from = factory.LazyFunction(lambda: datetime.date(2026, 1, 5))
    default_harvesting_day = 1  # Tuesday
    default_packing_day = 2  # Wednesday
    default_washing_day = 1  # Tuesday
    default_cleaning_day = 1  # Tuesday
    default_get_current_stock_day = 0  # Monday
    name = factory.LazyAttribute(lambda o: f"Day {o.day_number}")
    number_of_tours = 1


class OrdersDeliveryDayFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OrdersDeliveryDay

    day_number = factory.Sequence(lambda n: n % 7)
    default_harvesting_day = 1
    default_packing_day = 2
    default_washing_day = 1
    default_cleaning_day = 1


class DeliveryStationDayFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DeliveryStationDay

    delivery_station = factory.SubFactory(DeliveryStationFactory)
    delivery_day = factory.SubFactory(SharesDeliveryDayFactory)
    valid_from = factory.LazyFunction(lambda: datetime.date(2026, 1, 5))
    tour_number = 1


TOUR_NUMBER_CHECK = "commissioning_deliverystationday_tour_number_at_least_one"


def store_legacy_tour_number_zero(station_day: DeliveryStationDay) -> None:
    """Give ``station_day`` the tour 0 a row written before the
    ``tour_number >= 1`` check may still hold in production.

    The check is ``NOT VALID``, so it refuses the write; it is dropped for the
    write and added back the same way, inside the test's transaction. Postgres
    refuses an ALTER TABLE while the table's deferred foreign-key checks are
    pending, so those run first.
    """
    table = DeliveryStationDay._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute(f"ALTER TABLE {table} DROP CONSTRAINT {TOUR_NUMBER_CHECK}")
        cursor.execute(
            f"UPDATE {table} SET tour_number = 0 WHERE id = %s", [station_day.pk]
        )
        cursor.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {TOUR_NUMBER_CHECK} "
            "CHECK (tour_number >= 1) NOT VALID"
        )
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")
    station_day.refresh_from_db()
