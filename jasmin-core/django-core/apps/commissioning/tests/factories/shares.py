from __future__ import annotations

import datetime
from decimal import Decimal

import factory

from apps.commissioning.models import (
    DefaultShareContent,
    Share,
    ShareContent,
    ShareDelivery,
    ShareType,
    ShareTypeVariation,
    ShareTypeVariationGrossPrice,
    VirtualVariationComponent,
)
from apps.commissioning.models.choices_text import SizeOptions

from .basics import ShareArticleFactory
from .days import DeliveryStationDayFactory, SharesDeliveryDayFactory
from .delivery import DeliveryStationFactory


class ShareTypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ShareType
        django_get_or_create = ("share_option",)

    name = factory.Sequence(lambda n: f"Share Type {n}")
    share_option = "HARVEST_SHARE"
    valid_from = factory.LazyFunction(lambda: datetime.date(2026, 1, 5))
    delivery_cycle = "WEEKLY"


class ShareTypeVariationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ShareTypeVariation

    share_type = factory.SubFactory(ShareTypeFactory)
    variation_type = "physical"
    size = factory.Iterator([s.value for s in SizeOptions])
    valid_from = factory.LazyFunction(lambda: datetime.date(2026, 1, 5))
    sort_order = 0


class VirtualVariationComponentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = VirtualVariationComponent

    virtual_variation = factory.SubFactory(
        ShareTypeVariationFactory, variation_type="virtual"
    )
    physical_variation = factory.SubFactory(ShareTypeVariationFactory)
    quantity = Decimal("1.00")


class ShareTypeVariationGrossPriceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ShareTypeVariationGrossPrice

    share_type_variation = factory.SubFactory(ShareTypeVariationFactory)
    valid_from = factory.LazyFunction(lambda: datetime.date(2026, 1, 5))
    price_per_delivery = Decimal("10.00")
    tax_rate = Decimal("7.00")


class ShareFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Share

    year = 2026
    delivery_week = 15
    delivery_day = factory.SubFactory(SharesDeliveryDayFactory)
    share_type_variation = factory.SubFactory(ShareTypeVariationFactory)


class ShareContentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ShareContent

    share = factory.SubFactory(ShareFactory)
    share_article = factory.SubFactory(ShareArticleFactory)
    delivery_station = factory.SubFactory(DeliveryStationFactory)
    amount = Decimal("5.000")
    unit = "KG"
    size = "M"


class DefaultShareContentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DefaultShareContent

    year = 2026
    delivery_week = 15
    share_type_variation = factory.SubFactory(ShareTypeVariationFactory)
    share_article = factory.SubFactory(ShareArticleFactory)
    amount = Decimal("3.000")
    unit = "KG"
    size = "M"


class ShareDeliveryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ShareDelivery

    share = factory.SubFactory(ShareFactory)
    delivery_station_day = factory.SubFactory(DeliveryStationDayFactory)
