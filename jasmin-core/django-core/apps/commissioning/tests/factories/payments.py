from __future__ import annotations

import factory

from apps.commissioning.models import PaymentCycle


class PaymentCycleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PaymentCycle
        django_get_or_create = ("choice",)

    is_active = True
    choice = "MONTHLY"
