"""Pytest fixtures for the notifications app.

Re-exports the session-scoped tenant schema setup from the commissioning
app so that notifications tests can request the `tenant` fixture without
each app having to re-create its own schema.
"""

from __future__ import annotations

from apps.commissioning.tests.conftest import (  # noqa: F401
    _tenant_schema,
    tenant,
)
