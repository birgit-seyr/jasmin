"""Shared pytest fixtures for tenants app tests.

Re-uses the schema/tenant setup pattern from the commissioning test suite.
"""

from __future__ import annotations

import logging

import pytest
from django.db import connection
from rest_framework.test import APIClient

from apps.shared.tenants.models import Domain, Tenant


@pytest.fixture(scope="session")
def _tenant_schema(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        t = Tenant.objects.filter(schema_name="test_tenants").first()
        if t is None:
            t = Tenant(schema_name="test_tenants", name="Test Tenants Farm")
            t.save()
        if not Domain.objects.filter(domain="tenants-pytest.localhost").exists():
            Domain.objects.create(
                tenant=t, domain="tenants-pytest.localhost", is_primary=True
            )
        if not Domain.objects.filter(domain="testserver").exists():
            Domain.objects.create(tenant=t, domain="testserver")
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
def user(tenant):
    from apps.commissioning.tests.factories import JasminUserFactory

    return JasminUserFactory(roles=["office"])


@pytest.fixture()
def api_client(user):
    client = APIClient(HTTP_HOST="tenants-pytest.localhost")
    client.force_authenticate(user=user)
    return client


@pytest.fixture(autouse=True)
def _silence_django_request_logging():
    logger = logging.getLogger("django.request")
    prev = logger.level
    logger.setLevel(logging.CRITICAL)
    yield
    logger.setLevel(prev)
