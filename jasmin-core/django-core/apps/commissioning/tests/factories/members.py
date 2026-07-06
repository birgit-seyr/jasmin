from __future__ import annotations

import datetime

import factory
from django.utils import timezone

from apps.commissioning.models import (
    CoopShare,
    Member,
    Subscription,
)

from .days import DeliveryStationDayFactory
from .payments import PaymentCycleFactory
from .shares import ShareTypeVariationFactory


class MemberFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Member

    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    email = factory.Sequence(lambda n: f"member{n}@example.com")
    member_number = factory.Sequence(lambda n: n + 1000)
    is_active = True
    # Tenant-local (settings.TIME_ZONE) today, matching how production sets
    # entry_date (Member.save → timezone.localdate). Using OS-local
    # ``date.today()`` here skews against the UTC stamps near midnight.
    entry_date = factory.LazyFunction(timezone.localdate)


class CoopShareFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CoopShare

    member = factory.SubFactory(MemberFactory)
    amount_of_coop_shares = 1
    # Snapshot of the share's nominal value at acquisition — populated
    # in prod by the office UI from TenantSettings, but the factory
    # needs a non-null sentinel so the model's full_clean() passes.
    value_one_coop_share = 100


class SubscriptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Subscription

    member = factory.SubFactory(MemberFactory)
    share_type_variation = factory.SubFactory(ShareTypeVariationFactory)
    valid_from = factory.LazyFunction(lambda: datetime.date(2026, 1, 5))
    # A subscription must have a finite term (the model now rejects open-ended
    # ones). Default to a one-year Monday→Sunday span so factory-built subs are
    # valid without every caller spelling it out; tests that need a specific
    # window (or to assert the open-ended rejection) pass their own.
    valid_until = factory.LazyFunction(lambda: datetime.date(2027, 1, 3))
    quantity = 1
    payment_cycle = factory.SubFactory(PaymentCycleFactory)
    default_delivery_station_day = factory.SubFactory(DeliveryStationDayFactory)
