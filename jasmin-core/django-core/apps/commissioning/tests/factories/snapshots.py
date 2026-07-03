from __future__ import annotations

from decimal import Decimal

import factory
from django.utils import timezone

from apps.commissioning.models import CurrentStockBalance, StockSnapshot

from .basics import ShareArticleFactory, StorageFactory


class StockSnapshotFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StockSnapshot

    snapshot_date = factory.LazyFunction(timezone.now)
    share_article = factory.SubFactory(ShareArticleFactory)
    unit = "KG"
    size = "M"
    storage = factory.SubFactory(StorageFactory, is_short_term_harvest_storage=True)
    balance = Decimal("0.000")


class CurrentStockBalanceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CurrentStockBalance

    share_article = factory.SubFactory(ShareArticleFactory)
    unit = "KG"
    size = "M"
    storage = factory.SubFactory(StorageFactory, is_short_term_harvest_storage=True)
    balance = Decimal("0.000")
