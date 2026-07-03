from __future__ import annotations

import factory

from apps.commissioning.models import Market


class MarketFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Market

    is_active = True
    name = factory.Sequence(lambda n: f"Market {n}")
    slug = factory.LazyAttribute(lambda o: o.name.lower().replace(" ", "-"))
    day_number = 5  # Saturday
