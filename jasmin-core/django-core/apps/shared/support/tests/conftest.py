"""Pytest fixtures for support tests.

Re-exports the session-scoped tenant fixtures from the commissioning app (so the
schema is migrated once) and adds a public-schema ``super_admin`` fixture +
``factory`` for dispatching the admin viewset (mirrors super_admin/tests).
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django_tenants.utils import schema_context
from rest_framework.test import APIRequestFactory

from apps.commissioning.tests.conftest import (  # noqa: F401
    _silence_django_request_logging,
    _tenant_schema,
    anon_client,
    api_client,
    member_user,
    tenant,
    user,
)
from apps.shared.super_admin.models import SuperAdmin


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """Support create/reply carry ScopedRateThrottle scopes; wipe the buckets
    between tests so counters don't leak into the throttle test."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def super_admin(_tenant_schema):
    with schema_context("public"):
        admin, _ = SuperAdmin.objects.get_or_create(
            email="support-tests@example.com",
            defaults={"first_name": "Support", "last_name": "Tester"},
        )
    admin.is_super_admin = True
    admin.user_role = "super_admin"
    return admin


@pytest.fixture
def factory():
    return APIRequestFactory()
