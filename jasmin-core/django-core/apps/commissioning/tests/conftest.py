"""
Shared pytest fixtures for the commissioning app.

Usage:
    - `db` / `transactional_db`: standard pytest-django DB access
    - `tenant`: switches to the pre-created tenant schema (required for any model in TENANT_APPS)
    - `user`: authenticated JasminUser within the tenant schema
    - `api_client`: DRF APIClient authenticated as `user`
    - `api_request_factory`: DRF APIRequestFactory for unit-testing views without routing
"""

from __future__ import annotations

import logging

import pytest
from django.db import connection
from django.db.backends.postgresql.operations import (
    DatabaseOperations as PostgresDatabaseOperations,
)
from rest_framework.test import APIClient, APIRequestFactory

from apps.shared.tenants.models import Domain, Tenant

from .factories import JasminUserFactory

# ---------------------------------------------------------------------------
# Force CASCADE on the post-test ``flush`` triggered by
# ``@pytest.mark.django_db(transaction=True)``.
#
# django-tenants puts ``django.contrib.contenttypes`` in SHARED_APPS (its
# table lives in the public schema) and ``django.contrib.auth`` in
# TENANT_APPS (``auth_permission`` lives in every tenant schema). The
# auth_permission → django_content_type FK is therefore cross-schema.
#
# Django's default ``flush`` issues ``TRUNCATE <tables>`` without CASCADE,
# which Postgres refuses for any table that has a cross-schema referrer.
# CASCADE is harmless during test teardown — the contract of ``flush`` is
# already "wipe everything", and CASCADE just extends that to dependents.
#
# Patch the Postgres-specific override (the base class is shadowed by
# ``django.db.backends.postgresql.operations.DatabaseOperations.sql_flush``,
# so patching the base does nothing for real connections).
# ---------------------------------------------------------------------------
_original_sql_flush = PostgresDatabaseOperations.sql_flush


def _sql_flush_with_cascade(
    self, style, tables, *, reset_sequences=False, allow_cascade=False
):
    return _original_sql_flush(
        self, style, tables, reset_sequences=reset_sequences, allow_cascade=True
    )


PostgresDatabaseOperations.sql_flush = _sql_flush_with_cascade


@pytest.fixture(scope="session")
def _tenant_schema(django_db_setup, django_db_blocker):
    """Create the test-tenant schema ONCE per session.

    ``Tenant.save(auto_create_schema=True)`` runs full migrations on the new
    schema — expensive, but this only happens once per ``pytest`` invocation.

    Implemented as get-or-create because pytest resolves session-scoped
    fixtures per *defining* conftest. When the same fixture is re-exported
    from multiple conftests (accounts, authz, commissioning), pytest may
    invoke the setup more than once. Idempotent creation avoids the
    ``UNIQUE`` clash on ``tenants_tenant.schema_name``.
    """
    from django.core.management import call_command

    with django_db_blocker.unblock():
        t = Tenant.objects.filter(schema_name="test_pytest").first()
        if t is None:
            t = Tenant(schema_name="test_pytest", name="Test Farm")
            t.save()
        else:
            # Schema persists across pytest sessions. Re-apply any migrations
            # added since the schema was first created so newly-added apps
            # (e.g. payments) get their tables.
            call_command(
                "migrate_schemas",
                schema_name="test_pytest",
                interactive=False,
                verbosity=0,
            )
        if not Domain.objects.filter(domain="pytest.localhost").exists():
            Domain.objects.create(tenant=t, domain="pytest.localhost", is_primary=True)
        if not Domain.objects.filter(domain="testserver").exists():
            # "testserver" is Django's default test-client hostname
            Domain.objects.create(tenant=t, domain="testserver")
        connection.set_schema_to_public()
    yield t
    with django_db_blocker.unblock():
        # Only drop if this fixture instance owns the row (best-effort).
        try:
            t.delete()  # auto_drop_schema cleans up
        except Exception:
            pass


@pytest.fixture()
def tenant(_tenant_schema, db):
    """Switch DB connection to the pre-created tenant schema."""
    connection.set_tenant(_tenant_schema)
    yield _tenant_schema
    connection.set_schema_to_public()


@pytest.fixture()
def user(tenant):
    """Default authenticated tenant user — has the ``office`` role.

    Most viewsets require ``IsStaff`` (office/staff/admin/...) to read.
    Tests that need a different role profile (member, customer, anonymous)
    should create their own user via ``JasminUserFactory(roles=[...])``
    instead of relying on this default.
    """
    return JasminUserFactory(roles=["office"])


@pytest.fixture()
def member_user(tenant):
    """A tenant user with only the ``member`` role."""
    return JasminUserFactory(roles=["member"])


@pytest.fixture()
def anon_client():
    """Unauthenticated DRF APIClient."""
    return APIClient()


@pytest.fixture()
def api_client(user):
    """Authenticated DRF APIClient."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def make_step_up_token(user):
    """Mint an AccessToken carrying a fresh ``step_up_verified_at`` claim.

    Endpoints gated by ``apps.accounts.permissions.RequiresStepUp`` read
    that claim from ``request.auth.payload``. A bare
    ``force_authenticate(user=...)`` leaves ``request.auth=None`` (the
    same state as session auth in prod), so the gate raises
    ``StepUpRequired`` before the view runs. Pass this token as the
    ``token=`` arg to ``force_authenticate`` (both the ``APIClient`` and
    the ``APIRequestFactory`` form accept it) and the gate sees a fresh
    identity proof — exactly the state the real ``POST /api/auth/step-up/``
    rotation produces.
    """
    import time

    from rest_framework_simplejwt.tokens import AccessToken

    token = AccessToken.for_user(user)
    token["step_up_verified_at"] = int(time.time())
    return token


@pytest.fixture()
def step_up_client(user):
    """``api_client`` whose token carries a fresh step-up claim.

    Use on tests that exercise a ``RequiresStepUp``-gated endpoint past
    the gate (the gate itself is covered in
    ``apps/accounts/tests/test_step_up.py``).
    """
    client = APIClient()
    client.force_authenticate(user=user, token=make_step_up_token(user))
    return client


@pytest.fixture()
def api_request_factory():
    """DRF APIRequestFactory for building bare requests (no routing)."""
    return APIRequestFactory()


@pytest.fixture(autouse=True)
def _silence_django_request_logging():
    """Suppress Django's request error logging to avoid Python 3.14 copy() crash.

    Django 5.0's error-response logger triggers ``copy.copy()`` on template
    contexts, which is broken under Python 3.14 (``AttributeError: 'super'
    object has no attribute 'dicts'``). Silencing the logger prevents the
    crash while still letting tests assert on response status codes.
    """
    logger = logging.getLogger("django.request")
    prev = logger.level
    logger.setLevel(logging.CRITICAL)
    yield
    logger.setLevel(prev)
