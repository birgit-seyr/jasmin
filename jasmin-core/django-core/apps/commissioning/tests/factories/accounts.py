from __future__ import annotations

import factory

from apps.accounts.models import JasminUser


class JasminUserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = JasminUser

    username = factory.Sequence(lambda n: f"user{n}")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.com")
    is_active = True
    account_status = "active"
