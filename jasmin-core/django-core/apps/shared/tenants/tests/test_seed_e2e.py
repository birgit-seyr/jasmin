"""``seed_e2e`` provisions the Playwright suite's own tenants and nothing else.

The suite runs against a developer's dev database, next to the ``test`` tenant
they work in, so the command (and its ``--reset`` above all) must only ever
create, refresh or drop the schemas it names.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_tenants.utils import schema_context

from apps.commissioning.management.commands.seed_e2e_commissioning import (
    SHARE_TYPE_NAME,
)
from apps.commissioning.models import DeliveryStationDay, ShareType
from apps.shared.tenants.management.commands.seed_e2e import E2E_TENANTS
from apps.shared.tenants.models import Domain, Tenant, TenantSettings

pytestmark = pytest.mark.django_db

PERSONA_EMAILS = {
    "test-admin@example.com",
    "test-office@example.com",
    "test-member@example.com",
}


@pytest.fixture
def debug_on(settings):
    settings.DEBUG = True


def _seed(**options) -> None:
    call_command("seed_e2e", **options)


def test_seeds_english_personas_without_two_factor_and_is_idempotent(debug_on):
    _seed()

    for e2e_tenant in E2E_TENANTS:
        tenant = Tenant.objects.get(schema_name=e2e_tenant.schema)
        assert tenant.tenant_language == "en"
        assert Domain.objects.get(domain=e2e_tenant.domain).tenant_id == tenant.pk
        with schema_context(e2e_tenant.schema):
            users = get_user_model().objects.filter(email__in=PERSONA_EMAILS)
            assert {user.email for user in users} == PERSONA_EMAILS
            assert {user.user_language for user in users} == {"en"}

    first = E2E_TENANTS[0]
    with schema_context(first.schema):
        office = get_user_model().objects.get(email="test-office@example.com")
        TOTPDevice.objects.create(user=office, name="phone", confirmed=True)
        user_count = get_user_model().objects.count()

    _seed()

    assert Tenant.objects.filter(
        schema_name__in=[e2e_tenant.schema for e2e_tenant in E2E_TENANTS]
    ).count() == len(E2E_TENANTS)
    with schema_context(first.schema):
        assert get_user_model().objects.count() == user_count
        assert not TOTPDevice.objects.filter(user=office.pk).exists()
        assert ShareType.objects.filter(name=SHARE_TYPE_NAME).count() == 1
        assert DeliveryStationDay.objects.count() == 1
    current = TenantSettings.get_current_settings(
        Tenant.objects.get(schema_name=first.schema)
    )
    assert current is not None
    assert current.min_weeks_from_creation_to_start_delivery == 0
    assert current.min_number_coop_shares == 0
    with schema_context(E2E_TENANTS[1].schema):
        assert not ShareType.objects.exists()


def test_reset_recreates_only_the_e2e_tenants(debug_on, _tenant_schema):
    _seed()
    first = E2E_TENANTS[0]
    with schema_context(first.schema):
        get_user_model().objects.create_user(
            email="leftover@example.com",
            password="unused-Pass-123",
            first_name="Left",
            last_name="Over",
        )
    with schema_context(_tenant_schema.schema_name):
        bystander = get_user_model().objects.create_user(
            email="bystander@example.com",
            password="unused-Pass-123",
            first_name="By",
            last_name="Stander",
        )

    _seed(reset=True)

    with schema_context(first.schema):
        assert (
            not get_user_model().objects.filter(email="leftover@example.com").exists()
        )
    assert Tenant.objects.filter(pk=_tenant_schema.pk).exists()
    with schema_context(_tenant_schema.schema_name):
        assert get_user_model().objects.filter(pk=bystander.pk).exists()
