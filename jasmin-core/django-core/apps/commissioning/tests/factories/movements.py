from __future__ import annotations

from decimal import Decimal

import factory
from django.utils import timezone

from apps.commissioning.models import (
    MovementShareArticle,
)

from .basics import ShareArticleFactory, StorageFactory


class MovementShareArticleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MovementShareArticle

    date = factory.LazyFunction(timezone.now)
    movement_type = "HARVEST"
    share_article = factory.SubFactory(ShareArticleFactory)
    unit = "KG"
    size = "M"
    amount = Decimal("10.000")
    is_theoretical = False
    storage = factory.SubFactory(StorageFactory, is_short_term_harvest_storage=True)
