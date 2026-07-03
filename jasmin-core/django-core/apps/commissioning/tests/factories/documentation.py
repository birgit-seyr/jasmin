from __future__ import annotations

import factory

from apps.commissioning.models import (
    AdditionalTheoreticalCleanAmount,
    AdditionalTheoreticalHarvest,
    AdditionalTheoreticalPurchase,
    AdditionalTheoreticalWashAmount,
    CleanAmount,
    Forecast,
    ForecastShareTypeVariation,
    Harvest,
    Plot,
    Purchase,
    TheoreticalCleanAmount,
    TheoreticalHarvest,
    TheoreticalPurchase,
    TheoreticalWashAmount,
    WashAmount,
    Waste,
)

from .basics import ShareArticleFactory, StorageFactory
from .shares import ShareContentFactory, ShareTypeVariationFactory


class PlotFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Plot

    name = factory.Sequence(lambda n: f"Plot {n}")
    is_active = True


class ForecastFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Forecast

    year = 2026
    delivery_week = 15
    share_article = factory.SubFactory(ShareArticleFactory)
    amount = 100
    unit = "KG"
    size = "M"
    storage = factory.SubFactory(StorageFactory, is_short_term_harvest_storage=True)


class ForecastShareTypeVariationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ForecastShareTypeVariation

    forecast = factory.SubFactory(ForecastFactory)
    share_type_variation = factory.SubFactory(ShareTypeVariationFactory)


# ── Harvest ──


class TheoreticalHarvestFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TheoreticalHarvest

    year = 2026
    delivery_week = 15
    day_number = 1  # Tuesday
    share_article = factory.SubFactory(ShareArticleFactory)
    amount = 50
    unit = "KG"
    size = "M"
    storage = factory.SubFactory(StorageFactory, is_short_term_harvest_storage=True)
    share_content = factory.SubFactory(ShareContentFactory)
    forecast = factory.SubFactory(ForecastFactory)


class AdditionalTheoreticalHarvestFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AdditionalTheoreticalHarvest

    year = 2026
    delivery_week = 15
    day_number = 1
    share_article = factory.SubFactory(ShareArticleFactory)
    amount = 10
    unit = "KG"
    size = "M"
    storage = factory.SubFactory(StorageFactory, is_short_term_harvest_storage=True)


class HarvestFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Harvest

    year = 2026
    delivery_week = 15
    day_number = 1
    share_article = factory.SubFactory(ShareArticleFactory)
    unit = "KG"
    size = "M"
    storage = factory.SubFactory(StorageFactory, is_short_term_harvest_storage=True)


class WasteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Waste

    year = 2026
    delivery_week = 15
    day_number = 1
    share_article = factory.SubFactory(ShareArticleFactory)
    unit = "KG"
    size = "M"
    storage = factory.SubFactory(StorageFactory, is_short_term_harvest_storage=True)


# ── Purchase ──


class TheoreticalPurchaseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TheoreticalPurchase

    year = 2026
    delivery_week = 15
    share_article = factory.SubFactory(ShareArticleFactory, is_purchased=True)
    amount = 50
    unit = "KG"
    size = "M"
    storage = factory.SubFactory(StorageFactory, is_short_term_harvest_storage=True)
    share_content = factory.SubFactory(ShareContentFactory)


class AdditionalTheoreticalPurchaseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AdditionalTheoreticalPurchase

    year = 2026
    delivery_week = 15
    share_article = factory.SubFactory(ShareArticleFactory, is_purchased=True)
    amount = 10
    unit = "KG"
    size = "M"
    storage = factory.SubFactory(StorageFactory, is_short_term_harvest_storage=True)


class PurchaseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Purchase

    year = 2026
    delivery_week = 15
    share_article = factory.SubFactory(ShareArticleFactory, is_purchased=True)
    unit = "KG"
    size = "M"
    storage = factory.SubFactory(StorageFactory, is_short_term_harvest_storage=True)


# ── Wash ──


class TheoreticalWashAmountFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TheoreticalWashAmount

    year = 2026
    delivery_week = 15
    day_number = 1
    share_article = factory.SubFactory(ShareArticleFactory)
    amount = 50
    unit = "KG"
    size = "M"
    storage = factory.SubFactory(StorageFactory, is_short_term_harvest_storage=True)
    share_content = factory.SubFactory(ShareContentFactory)


class AdditionalTheoreticalWashAmountFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AdditionalTheoreticalWashAmount

    year = 2026
    delivery_week = 15
    day_number = 1
    share_article = factory.SubFactory(ShareArticleFactory)
    amount = 10
    unit = "KG"
    size = "M"
    storage = factory.SubFactory(StorageFactory, is_short_term_harvest_storage=True)


class WashAmountFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = WashAmount

    year = 2026
    delivery_week = 15
    day_number = 1
    share_article = factory.SubFactory(ShareArticleFactory)
    unit = "KG"
    size = "M"
    storage = factory.SubFactory(StorageFactory, is_short_term_harvest_storage=True)


# ── Clean ──


class TheoreticalCleanAmountFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TheoreticalCleanAmount

    year = 2026
    delivery_week = 15
    day_number = 1
    share_article = factory.SubFactory(ShareArticleFactory)
    amount = 50
    unit = "KG"
    size = "M"
    storage = factory.SubFactory(StorageFactory, is_short_term_harvest_storage=True)
    share_content = factory.SubFactory(ShareContentFactory)


class AdditionalTheoreticalCleanAmountFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AdditionalTheoreticalCleanAmount

    year = 2026
    delivery_week = 15
    day_number = 1
    share_article = factory.SubFactory(ShareArticleFactory)
    amount = 10
    unit = "KG"
    size = "M"
    storage = factory.SubFactory(StorageFactory, is_short_term_harvest_storage=True)


class CleanAmountFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CleanAmount

    year = 2026
    delivery_week = 15
    day_number = 1
    share_article = factory.SubFactory(ShareArticleFactory)
    unit = "KG"
    size = "M"
    storage = factory.SubFactory(StorageFactory, is_short_term_harvest_storage=True)
