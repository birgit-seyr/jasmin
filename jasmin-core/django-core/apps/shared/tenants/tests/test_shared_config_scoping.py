"""SEC-14: ``TenantSettings`` and ``TenantEmailConfig`` live in SHARED_APPS
(the public schema), so they are NOT protected by django-tenants schema
isolation — every read MUST carry a tenant scope. These tests assert the
scoped chokepoints (``get_current_settings`` / ``get_active_for_schema``)
never return another tenant's row.
"""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context

from apps.shared.tenants.models import Tenant, TenantEmailConfig, TenantSettings


def _second_tenant() -> Tenant:
    """A second Tenant row WITHOUT provisioning a schema. TenantEmailConfig
    and TenantSettings are SHARED (public-schema) tables, so we only need a
    second FK target, not a migrated schema (auto_create_schema=False emits
    no DDL). django-tenants refuses to create a Tenant unless the connection
    is on the public schema, so do it under a public schema_context (the
    ``tenant`` fixture leaves us on the tenant schema)."""
    with schema_context(get_public_schema_name()):
        other = Tenant(schema_name="sec14_other", name="Other Farm")
        other.auto_create_schema = False
        other.save()
    return other


@pytest.mark.django_db
class TestSharedConfigTenantScoping:
    def test_email_config_get_active_for_schema_is_tenant_scoped(self, tenant):
        other = _second_tenant()
        TenantEmailConfig.objects.create(
            tenant=tenant, from_email="a@example.com", from_name="A", is_active=True
        )
        TenantEmailConfig.objects.create(
            tenant=other, from_email="b@example.com", from_name="B", is_active=True
        )

        a = TenantEmailConfig.get_active_for_schema(tenant.schema_name)
        b = TenantEmailConfig.get_active_for_schema("sec14_other")

        assert a is not None and a.tenant_id == tenant.id
        assert b is not None and b.tenant_id == other.id
        # The chokepoint never bleeds one tenant's config into the other's.
        assert a.id != b.id
        assert a.from_email == "a@example.com"

    def test_email_config_unknown_schema_returns_none(self, tenant):
        assert TenantEmailConfig.get_active_for_schema("does_not_exist") is None

    def test_email_config_ignores_inactive(self, tenant):
        TenantEmailConfig.objects.create(
            tenant=tenant, from_email="a@example.com", from_name="A", is_active=False
        )
        assert TenantEmailConfig.get_active_for_schema(tenant.schema_name) is None

    def test_tenant_settings_get_current_is_tenant_scoped(self, tenant):
        now = timezone.now()
        other = _second_tenant()
        TenantSettings.objects.create(
            tenant=tenant, valid_from=now - datetime.timedelta(days=1)
        )
        TenantSettings.objects.create(
            tenant=other, valid_from=now - datetime.timedelta(days=1)
        )

        a = TenantSettings.get_current_settings(tenant)
        b = TenantSettings.get_current_settings(other)

        assert a is not None and a.tenant_id == tenant.id
        assert b is not None and b.tenant_id == other.id
        assert a.id != b.id

    def test_get_current_settings_resolves_fake_tenant_by_schema_name(self, tenant):
        """TEN-2: a schema-bearing stand-in (the django-tenants FakeTenant that
        ``schema_context`` puts on a Huey worker / management command) resolves
        to the real Tenant instead of str()-coercing the CharField-PK FK and
        silently returning None — which callers read as 'no settings' and fall
        back to hardcoded defaults."""
        now = timezone.now()
        TenantSettings.objects.create(
            tenant=tenant, valid_from=now - datetime.timedelta(days=1)
        )

        class _FakeTenant:  # not a Tenant model — mimics connection.tenant on a worker
            schema_name = tenant.schema_name

        resolved = TenantSettings.get_current_settings(_FakeTenant())
        assert resolved is not None
        assert resolved.tenant_id == tenant.id

    def test_get_current_settings_rejects_stand_in_without_schema(self, tenant):
        """TEN-2 fail-closed: a non-Tenant with no ``schema_name`` is a
        programming error, not 'no settings' — raise instead of a misleading
        None."""
        with pytest.raises(TypeError):
            TenantSettings.get_current_settings(object())
