from __future__ import annotations

import datetime
from decimal import Decimal

import factory

from apps.commissioning.models import (
    DeliveryNoteContent,
    DeliveryNoteReseller,
    InvoiceReseller,
    Offer,
    OfferGroup,
    Order,
    OrderContent,
    Reseller,
)

from .basics import ContactEntityFactory, ShareArticleFactory


class OfferGroupFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OfferGroup

    is_active = True
    # Start well above the seeded default offer group's number (1) so factory
    # rows never collide with it on the unique ``number``.
    number = factory.Sequence(lambda n: n + 1001)
    name = factory.Sequence(lambda n: f"Offer Group {n}")


class ResellerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Reseller

    contact = factory.SubFactory(ContactEntityFactory)
    is_reseller = True
    is_active_reseller = True
    customer_number = factory.Sequence(lambda n: n + 100)


class OfferFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Offer

    year = 2026
    delivery_week = 15
    share_article = factory.SubFactory(ShareArticleFactory)
    unit = "KG"
    size = "M"
    amount_per_pu = Decimal("1.000")
    amount = Decimal("100.000")
    offer_group = factory.SubFactory(OfferGroupFactory)


class OrderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Order

    year = 2026
    delivery_week = 15
    day_number = 2  # Wednesday
    reseller = factory.SubFactory(ResellerFactory)


class OrderContentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OrderContent

    order = factory.SubFactory(OrderFactory)
    share_article = factory.SubFactory(ShareArticleFactory)
    amount = Decimal("10.000")
    unit = "KG"
    size = "M"
    # tax_rate is now non-null on every line item — see
    # apps/commissioning/utils/tax_rate_utils.py for the canonical
    # resolution chain. Tests that need a specific rate should override.
    tax_rate = Decimal("7.00")


class DeliveryNoteResellerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DeliveryNoteReseller

    order = factory.SubFactory(OrderFactory)
    # ``DeliveryNoteReseller.save`` now refuses ``date=None`` (was a
    # silent today-default — a GoBD audit hazard). Provide a stable
    # per-call default here so existing tests keep working; pass
    # ``date=...`` explicitly to test date-resolution behaviour, or
    # ``date=None`` to test the raise.
    date = factory.LazyFunction(datetime.date.today)


class DeliveryNoteContentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DeliveryNoteContent

    delivery_note = factory.SubFactory(DeliveryNoteResellerFactory)
    share_article = factory.SubFactory(ShareArticleFactory)
    amount = Decimal("10.000")
    unit = "KG"
    size = "M"
    tax_rate = Decimal("7.00")


class InvoiceResellerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = InvoiceReseller

    reseller = factory.SubFactory(ResellerFactory)
    # See ``DeliveryNoteResellerFactory.date``.
    date = factory.LazyFunction(datetime.date.today)
