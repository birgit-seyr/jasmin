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

import copy
import logging
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from django.db import connection, models
from django.db.backends.postgresql.operations import (
    DatabaseOperations as PostgresDatabaseOperations,
)
from rest_framework.test import APIClient, APIRequestFactory

from apps.shared.tenants.models import Domain, Tenant

from .factories import JasminUserFactory


# ---------------------------------------------------------------------------
# Make the post-test ``flush`` of ``@pytest.mark.django_db(transaction=True)``
# truncate nothing.
#
# ``flush`` truncates the tables of the schema the connection is on, and every
# test ends on the public schema, so it never reaches the ``test_pytest`` rows a
# transactional test commits. What it would truncate is the suite's own state:
# the session tenants and their domains, the seeded ops checklist, and
# ``django_content_type``, whose truncation cascades into every tenant schema's
# ``auth_permission`` and audit log. A transactional test's rows outlive it, and
# the next one measures from what is there.
#
# Patch the Postgres-specific override (the base class is shadowed by
# ``django.db.backends.postgresql.operations.DatabaseOperations.sql_flush``,
# so patching the base does nothing for real connections).
# ---------------------------------------------------------------------------
def _sql_flush_nothing(
    self, style, tables, *, reset_sequences=False, allow_cascade=False
):
    return []


PostgresDatabaseOperations.sql_flush = _sql_flush_nothing


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
        # ``testserver`` is Django's default test-client hostname, and this
        # tenant owns it for the whole suite: a routed request built with a
        # bare ``APIClient()`` resolves here. Exactly one ``Domain`` row can
        # hold a given hostname, so no other conftest may seed ``testserver``
        # — a second seeder would win or lose by load order and route those
        # requests into a different schema. Tests for another tenant address
        # it by its own host instead.
        #
        # update_or_create, not get-or-skip: the schema outlives a pytest
        # session, so a stale row left pointing at another tenant must be
        # repointed rather than silently accepted.
        #
        # ``is_primary`` is stated on both rows because ``DomainMixin.save``
        # force-promotes whichever row it writes while the tenant has no
        # primary yet — leaving it implicit makes the winner depend on whether
        # the rows already existed. ``testserver`` is the primary, so
        # ``frontend_base_url()`` (invitation / GDPR / password-reset links)
        # renders the same host a bare ``APIClient()`` request arrives on.
        Domain.objects.update_or_create(
            domain="pytest.localhost", defaults={"tenant": t, "is_primary": False}
        )
        Domain.objects.update_or_create(
            domain="testserver", defaults={"tenant": t, "is_primary": True}
        )
        connection.set_schema_to_public()
    yield t
    with django_db_blocker.unblock():
        # Only drop if this fixture instance owns the row (best-effort).
        try:
            t.delete()  # auto_drop_schema cleans up
        except Exception:
            pass


@contextmanager
def tenant_fields_restored(tenant: Tenant) -> Iterator[None]:
    """Put back whatever a test sets on the session-wide tenant object — a
    rate-limit override, a language, a logo. The rollback only undoes what
    reached the database, and tests run in random order."""
    saved = {}
    for field in tenant._meta.concrete_fields:
        value = getattr(tenant, field.attname)
        if isinstance(field, models.FileField):
            saved[field.attname] = value.name
        else:
            saved[field.attname] = copy.deepcopy(value)
    try:
        yield
    finally:
        for attname, value in saved.items():
            setattr(tenant, attname, value)


@pytest.fixture()
def tenant(_tenant_schema, db):
    """Switch DB connection to the pre-created tenant schema."""
    with tenant_fields_restored(_tenant_schema):
        connection.set_tenant(_tenant_schema)
        yield _tenant_schema
        connection.set_schema_to_public()


@pytest.fixture()
def email_config(tenant):
    """Give the test tenant an SMTP host of its own, for the office actions that
    refuse to run without one (``assert_tenant_can_send_email``). Nothing is
    sent: the emails are deferred to ``on_commit``, which the test transaction
    never reaches. Modules that check what is sent define their own
    ``email_config``, with an in-memory outbox."""
    from apps.shared.tenants.models import TenantEmailConfig

    config, _ = TenantEmailConfig.objects.update_or_create(
        tenant=tenant,
        defaults={
            "smtp_host": "smtp.example.org",
            "from_email": "office@example.org",
            "is_active": True,
        },
    )
    return config


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
def anon_client(_tenant_schema):
    """Unauthenticated DRF APIClient.

    Its requests go to ``testserver``, so it needs the tenant that owns that
    host to exist, even when no other fixture of the test has created it yet.
    """
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
