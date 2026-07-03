"""Pytest fixtures shared across payments tests.

Re-exports the session-scoped tenant fixtures from the commissioning app
(see `apps/commissioning/tests/conftest.py`) so payments tests can use
the same `tenant`, `user`, `member_user`, and `api_client` machinery
without duplicating schema setup.

Adds payments-specific fixtures:
    - `tenant_settings`   the active TenantSettings row for the test tenant
    - `member`            a Member with linked JasminUser (member role)
    - `billing_profile`   a SEPA-ready BillingProfile for `member`
    - `subscription`      a 1-year subscription for `member`
    - `member_api_client` APIClient authenticated as the member user
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

# Re-use the schema/session fixtures from commissioning so we don't migrate twice.
from apps.commissioning.tests.conftest import (  # noqa: F401
    _silence_django_request_logging,
    _tenant_schema,
    anon_client,
    api_client,
    api_request_factory,
    member_user,
    tenant,
    user,
)
from apps.commissioning.tests.factories import (
    JasminUserFactory,
    MemberFactory,
    PaymentCycleFactory,
    SubscriptionFactory,
)
from apps.payments.constants import PaymentMethodOptions
from apps.payments.models import BillingProfile
from apps.shared.tenants.models import TenantSettings


@pytest.fixture()
def tenant_settings(tenant):
    """Create the current TenantSettings row with sane billing defaults.

    Using `EXACT_PER_PERIOD` and `bills_joker_deliveries=False` matches the
    documented production defaults. Tests that need other values should
    update the returned object and call `.save()`.
    """
    now = timezone.now()
    ts = TenantSettings.objects.create(
        tenant=tenant,
        valid_from=now - datetime.timedelta(days=1),
        billing_strategy=TenantSettings.BILLING_STRATEGY_EXACT,
        bills_joker_deliveries=False,
        billing_due_day_of_month=1,
    )
    # SEPA creditor identity lives on Tenant (not TenantSettings).
    tenant.iban = "DE89370400440532013000"
    tenant.sepa_creditor_id = "DE98ZZZ09999999999"
    tenant.sepa_creditor_name = "Test Farm e.G."
    # Real BIC for COMMERZBANK AG — sepaxml validates the config's BIC
    # against a regex; any well-formed 8/11-char value works for the
    # test fixture.
    tenant.sepa_creditor_bic = "COBADEFFXXX"
    tenant.save()
    return ts


@pytest.fixture()
def member(tenant):
    """Tenant Member with a linked JasminUser holding the `member` role."""
    user = JasminUserFactory(roles=["member"])
    return MemberFactory(user=user)


@pytest.fixture()
def member_api_client(member):
    """APIClient authenticated as `member.user`."""
    client = APIClient()
    client.force_authenticate(user=member.user)
    return client


@pytest.fixture()
def billing_profile(member):
    """A fully-valid SEPA Direct Debit profile for `member`."""
    return BillingProfile.objects.create(
        member=member,
        payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
        iban="DE89370400440532013000",
        account_holder=f"{member.first_name} {member.last_name}",
        sepa_mandate_reference=f"MND-{member.pk}",
        sepa_mandate_signed_at=datetime.date(2026, 1, 1),
        is_active=True,
    )


@pytest.fixture()
def subscription(tenant, member):
    """A subscription for `member`, monthly cycle, 1-year term, 10€/delivery.

    `valid_from`/`valid_until` must align with the period mixin's week
    boundaries (Monday→Sunday). 2026-01-05 is a Monday; 2026-12-27 is a
    Sunday. SubscriptionFactory builds its own `default_delivery_station_day`
    (which transitively creates a `SharesDeliveryDay` with day_number=2),
    so we don't pre-create one here — doing so would clash on
    overlap_unique_fields=("day_number",).
    """
    return SubscriptionFactory(
        member=member,
        valid_from=datetime.date(2026, 1, 5),
        valid_until=datetime.date(2026, 12, 27),
        quantity=1,
        price_per_delivery=Decimal("10.00"),
        payment_cycle=PaymentCycleFactory(choice="MONTHLY"),
    )
