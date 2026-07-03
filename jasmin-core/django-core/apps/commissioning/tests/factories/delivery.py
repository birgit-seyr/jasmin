from __future__ import annotations

import datetime

import factory

from apps.commissioning.models import (
    DeliveryExceptionPeriod,
    DeliveryStation,
)


class DeliveryStationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DeliveryStation

    is_active = True
    short_name = factory.Sequence(lambda n: f"Station {n}")
    number = factory.Sequence(lambda n: n + 1)


class DeliveryExceptionPeriodFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DeliveryExceptionPeriod

    # String path (resolved lazily by factory_boy) avoids a circular import:
    # shares → days → … would re-enter this module at import time.
    share_type_variation = factory.SubFactory(
        "apps.commissioning.tests.factories.shares.ShareTypeVariationFactory"
    )
    valid_from = factory.LazyFunction(lambda: datetime.date(2026, 7, 6))  # Monday
    valid_until = factory.LazyFunction(lambda: datetime.date(2026, 7, 19))  # Sunday
    note = "Holiday break"
