"""Tenant-aware view of Django's ``connection``.

``django_tenants`` substitutes its own ``DatabaseWrapper`` for the stock
PostgreSQL one and hangs two attributes off it — ``schema_name`` and
``tenant`` — which the rest of this codebase reads constantly. ``django-stubs``
types ``django.db.connection`` as the plain ``BaseDatabaseWrapper``, which
declares neither, so every read is reported as a nonexistent attribute even
though it is the documented django-tenants API.

Import ``connection`` from here instead of from ``django.db`` in tenant-aware
code. At runtime this module re-exports the very same proxy object, so there is
no behavioural difference whatsoever; it exists only so the two attributes are
declared once rather than suppressed at every read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import connection as _django_connection

if TYPE_CHECKING:
    from django.db.backends.base.base import BaseDatabaseWrapper

    class TenantDatabaseWrapper(BaseDatabaseWrapper):
        """The two attributes ``django_tenants.DatabaseWrapper`` adds."""

        # Assigned by ``set_tenant`` / ``set_schema``. Genuinely ``None`` only
        # between wrapper construction and the first schema switch — a state no
        # request or task path can observe, because django-tenants raises
        # ``ImproperlyConfigured`` from ``_cursor`` while it holds.
        schema_name: str

        # A real ``Tenant`` row under ``TenantMainMiddleware`` / ``tenant_context``,
        # a django-tenants ``FakeTenant`` (schema name only, not a Model) under
        # ``schema_context`` in Huey workers and management commands, or ``None``
        # before the first switch. Deliberately ``Any``: narrowing it to ``Tenant``
        # would assert a row that half the call paths do not have.
        tenant: Any

    connection: TenantDatabaseWrapper
else:
    connection = _django_connection

__all__ = ["connection"]
