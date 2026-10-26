"""Pytest fixtures shared across cultivation tests.

Re-exports the session-scoped tenant fixtures from the commissioning app
(see ``apps/commissioning/tests/conftest.py``) so cultivation tests use the same
``tenant``/``user``/``api_client`` machinery instead of migrating a second schema.

``_tenant_schema`` must be re-imported alongside ``tenant``: pytest resolves a
re-exported fixture's own dependencies against the conftest that DEFINES it, so
leaving the session-scoped schema fixture out would leave ``tenant`` pointing at
nothing.
"""

from __future__ import annotations

from apps.commissioning.tests.conftest import (  # noqa: F401
    _silence_django_request_logging,
    _tenant_schema,
    anon_client,
    api_client,
    api_request_factory,
    tenant,
    user,
)
