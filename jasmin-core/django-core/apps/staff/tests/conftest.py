"""Pytest fixtures for the staff app.

Re-exports the session-scoped tenant/auth fixtures from the commissioning app
(see ``apps/commissioning/tests/conftest.py``) so staff tests reuse the same
``tenant`` / ``user`` / ``member_user`` / ``api_client`` machinery without
migrating a second schema.
"""

from __future__ import annotations

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
