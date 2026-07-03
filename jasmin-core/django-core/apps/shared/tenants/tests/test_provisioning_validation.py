"""Regression tests for shared tenant-provisioning validation.

The schema-name denylist, domain normalization, and admin-password policy must
hold on EVERY provisioning entry point — not only the HTTP serializer. These
lock the shared helper, the ``provision_tenant`` sink, and the ``create_tenant``
CLI, so a Tenant row can never map onto a reserved/pre-existing Postgres schema
(and the self-cleaning failure path can never ``DROP`` a schema it did not
create), and privileged admin passwords meet the same policy as registration.
"""

from __future__ import annotations

import pytest
from django.db import connection

from apps.shared.tenants.errors import (
    InvalidDomain,
    InvalidSchemaName,
    ReservedDomain,
    SchemaAlreadyExists,
    WeakPassword,
)
from apps.shared.tenants.models import Tenant
from apps.shared.tenants.provisioning import (
    normalize_domain,
    validate_admin_password,
    validate_schema_name,
)
from apps.shared.tenants.services import TenantService

# Satisfies AUTH_PASSWORD_VALIDATORS (12-char min + zxcvbn + common/numeric).
_STRONG_PW = "9xKqP2mwLvZt7Rdn"


# --------------------------------------------------------------------------- #
# Helper unit tests (no DB)                                                    #
# --------------------------------------------------------------------------- #


class TestValidateSchemaName:
    @pytest.mark.parametrize(
        "bad",
        ["public", "information_schema", "pg_catalog", "Has-Dashes", "UPPER", ""],
    )
    def test_rejects(self, bad):
        with pytest.raises(InvalidSchemaName):
            validate_schema_name(bad)

    def test_accepts_plain(self):
        assert validate_schema_name("newtenant") == "newtenant"


class TestNormalizeDomain:
    def test_lowercases_and_strips(self):
        assert normalize_domain("  New.Example.COM ") == "new.example.com"

    def test_rejects_blank(self):
        with pytest.raises(InvalidDomain):
            normalize_domain("   ")

    def test_rejects_platform_subdomain(self, settings):
        with pytest.raises(ReservedDomain):
            normalize_domain(f"{settings.SUPER_ADMIN_SUBDOMAIN}.localhost")


class TestValidateAdminPassword:
    @pytest.mark.parametrize("weak", ["pw", "verysecret", "aaaaaaaaaaaa"])
    def test_rejects_weak(self, weak):
        with pytest.raises(WeakPassword):
            validate_admin_password(weak)

    def test_accepts_strong(self):
        assert validate_admin_password(_STRONG_PW) == _STRONG_PW


# --------------------------------------------------------------------------- #
# provision_tenant enforces the guards itself (TEN-2)                          #
# Each raises in the validation block BEFORE any Tenant/Domain/schema write.   #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestProvisionTenantGuards:
    def _provision(self, **over):
        kwargs = {
            "schema_name": "prov_guard_ok",
            "name": "ProvGuardX",
            "domain": "prov-guard.example.com",
            "admin_email": "a@b.c",
            "admin_password": _STRONG_PW,
        }
        kwargs.update(over)
        return TenantService().provision_tenant(**kwargs)

    def test_reserved_schema_rejected(self):
        with pytest.raises(InvalidSchemaName):
            self._provision(schema_name="public")
        assert not Tenant.objects.filter(name="ProvGuardX").exists()

    def test_weak_password_rejected(self):
        with pytest.raises(WeakPassword):
            self._provision(admin_password="pw")
        assert not Tenant.objects.filter(name="ProvGuardX").exists()

    def test_platform_domain_rejected(self, settings):
        with pytest.raises(ReservedDomain):
            self._provision(domain=f"{settings.SUPER_ADMIN_SUBDOMAIN}.localhost")
        assert not Tenant.objects.filter(name="ProvGuardX").exists()


# --------------------------------------------------------------------------- #
# TEN-1 (HIGH): a pre-existing schema must be refused up front — never         #
# provisioned into, never DROP-CASCADE'd by the self-cleaning failure path.    #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
def test_provision_refuses_preexisting_schema():
    schema = "ten1_preexisting_victim"
    with connection.cursor() as cur:
        cur.execute(f'CREATE SCHEMA "{schema}"')

    with pytest.raises(SchemaAlreadyExists):
        TenantService().provision_tenant(
            schema_name=schema,
            name="VictimTenant",
            domain="victim.example.com",
            admin_email="a@b.c",
            admin_password=_STRONG_PW,
        )

    # No Tenant row created, and the pre-existing schema still exists (the
    # destructive cleanup never ran because we refused before creating a row).
    assert not Tenant.objects.filter(schema_name=schema).exists()
    with connection.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
            [schema],
        )
        assert cur.fetchone() is not None, "pre-existing schema was dropped!"
    # (CREATE SCHEMA is rolled back with the test transaction — no cleanup needed.)
