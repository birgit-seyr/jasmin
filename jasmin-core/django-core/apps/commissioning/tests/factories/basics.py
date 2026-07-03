from __future__ import annotations

import datetime
from decimal import Decimal

import factory

from apps.commissioning.models import (
    ContactEntity,
    Crate,
    CrateNetPrice,
    Season,
    ShareArticle,
    ShareArticleNetPrice,
    Storage,
)


class SeasonFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Season

    valid_from = factory.LazyFunction(lambda: datetime.date(2026, 1, 5))  # a Monday
    valid_until = factory.LazyFunction(lambda: datetime.date(2026, 12, 27))  # a Sunday
    weeks_without_delivery = factory.LazyFunction(list)


class StorageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Storage

    name = factory.Sequence(lambda n: f"Storage {n}")
    is_active = True
    is_long_term_harvest_storage = False
    is_short_term_harvest_storage = False

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        # ``Storage`` enforces a single short-term and a single long-term
        # harvest storage per tenant via partial unique indexes. Reuse the
        # existing singleton instead of failing when a test indirectly
        # creates two of them through SubFactory chains.
        if kwargs.get("is_short_term_harvest_storage"):
            existing = model_class.objects.filter(
                is_short_term_harvest_storage=True
            ).first()
            if existing is not None:
                return existing
        if kwargs.get("is_long_term_harvest_storage"):
            existing = model_class.objects.filter(
                is_long_term_harvest_storage=True
            ).first()
            if existing is not None:
                return existing
        return super()._create(model_class, *args, **kwargs)


class ShareArticleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ShareArticle

    name = factory.Sequence(lambda n: f"Article {n}")
    is_active = True
    is_purchased = False
    is_sold_to_resellers = False
    for_markets = False
    default_movement_unit = "KG"
    share_option = "HARVEST_SHARE"


class ShareArticleNetPriceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ShareArticleNetPrice

    share_article = factory.SubFactory(ShareArticleFactory)
    valid_from = factory.LazyFunction(lambda: datetime.date(2026, 1, 5))
    tax_rate = Decimal("7.00")


class CrateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Crate

    name = factory.Sequence(lambda n: f"Crate {n}")
    is_active = True
    number = factory.Sequence(lambda n: n + 1)


class CrateNetPriceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CrateNetPrice

    crate = factory.SubFactory(CrateFactory)
    valid_from = factory.LazyFunction(lambda: datetime.date(2026, 1, 5))
    price = Decimal("2.50")
    tax_rate = Decimal("19.00")


class ContactEntityFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ContactEntity

    company_name = factory.Sequence(lambda n: f"Company {n}")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    email = factory.LazyAttribute(
        lambda o: f"{o.first_name}.{o.last_name}@example.com".lower()
    )
