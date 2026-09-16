"""Shared pytest fixtures for tenants app tests.

Re-uses the schema/tenant setup pattern from the commissioning test suite.

Host resolution
---------------
``TenantMainMiddleware`` picks the schema from the request's ``Host`` header,
so every routed test in this package must address its tenant by name via
``TENANT_HOST`` / the ``tenant_host`` fixture. This package deliberately does
NOT claim Django's default test hostname ``testserver``: that ``Domain`` row
belongs to the commissioning test tenant (``test_pytest``). A ``Domain.domain``
is unique, so two conftests seeding ``testserver`` behind an "if not exists"
guard would hand ownership to whichever conftest loaded first and silently
route this package's requests into the other tenant's schema.
"""

from __future__ import annotations

import logging

import pytest
from django.db import connection
from rest_framework.test import APIClient

from apps.shared.tenants.models import Domain, Tenant

# The only hostname that resolves to this package's tenant schema.
TENANT_HOST = "tenants-pytest.localhost"


@pytest.fixture(scope="session")
def _tenant_schema(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        t = Tenant.objects.filter(schema_name="test_tenants").first()
        if t is None:
            t = Tenant(schema_name="test_tenants", name="Test Tenants Farm")
            t.save()
        # update_or_create, not get-or-skip: the schema outlives a pytest
        # session, so a stale row left pointing at another tenant must be
        # repointed rather than silently accepted.
        Domain.objects.update_or_create(
            domain=TENANT_HOST, defaults={"tenant": t, "is_primary": True}
        )
        connection.set_schema_to_public()
    yield t
    with django_db_blocker.unblock():
        try:
            t.delete()
        except Exception:
            pass


@pytest.fixture()
def tenant(_tenant_schema, db):
    connection.set_tenant(_tenant_schema)
    yield _tenant_schema
    connection.set_schema_to_public()


@pytest.fixture()
def tenant_host(tenant) -> str:
    """Hostname a routed request must use to land in ``tenant``'s schema.

    Fails the test at setup — rather than letting it pass against some other
    tenant's data — if the ``Domain`` row no longer maps to this schema.
    """
    domain = Domain.objects.filter(domain=TENANT_HOST).select_related("tenant").first()
    assert domain is not None, (
        f"No Domain row for {TENANT_HOST!r}; a routed request would 404 in "
        f"TenantMainMiddleware instead of reaching {tenant.schema_name!r}."
    )
    assert domain.tenant.schema_name == tenant.schema_name, (
        f"{TENANT_HOST!r} resolves to schema "
        f"{domain.tenant.schema_name!r}, not {tenant.schema_name!r} — routed "
        f"tests in this package would run against the wrong tenant."
    )
    return TENANT_HOST


@pytest.fixture()
def user(tenant):
    from apps.commissioning.tests.factories import JasminUserFactory

    return JasminUserFactory(roles=["office"])


@pytest.fixture()
def api_client(user, tenant_host):
    client = APIClient(HTTP_HOST=tenant_host)
    client.force_authenticate(user=user)
    return client


@pytest.fixture(autouse=True)
def _silence_django_request_logging():
    logger = logging.getLogger("django.request")
    prev = logger.level
    logger.setLevel(logging.CRITICAL)
    yield
    logger.setLevel(prev)
