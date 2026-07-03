from __future__ import annotations

import datetime

import factory

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
