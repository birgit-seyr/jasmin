from __future__ import annotations

from decimal import Decimal

import factory

from apps.commissioning.models import (
    Market,
    MarketArticle,
    MarketPrice,
    MarketProductGroup,
    ScaleTaxCode,
)

from .basics import ShareArticleFactory


class MarketFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Market

    is_active = True
    name = factory.Sequence(lambda n: f"Market {n}")
    day_number = 5  # Saturday


class MarketProductGroupFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MarketProductGroup

    number = factory.Sequence(lambda n: n + 1)
    name = factory.Sequence(lambda n: f"Group {n}")


class ScaleTaxCodeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ScaleTaxCode
        # A rate has one code, so PLUs built in one test share it.
        django_get_or_create = ("tax_rate",)

    tax_rate = Decimal("7.00")
    code = 1


class MarketArticleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MarketArticle

    plu_number = factory.Sequence(lambda n: n + 100)
    share_article = factory.SubFactory(ShareArticleFactory)
    scale_tax_code = factory.SubFactory(ScaleTaxCodeFactory)
    unit = "KG"
    name = factory.Sequence(lambda n: f"PLU {n}")


class MarketPriceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MarketPrice

    year = 2025
    delivery_week = 10
    market_article = factory.SubFactory(MarketArticleFactory)
    gross_price = Decimal("2.99")
