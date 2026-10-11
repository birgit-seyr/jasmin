"""Find a tenant by its schema name.

Under ``schema_context`` — Huey tasks, management commands — the active tenant
is a ``FakeTenant`` that carries only ``schema_name``, so code that needs the
real ``Tenant`` row (its domains, its settings) looks it up by that name.
"""

from __future__ import annotations

from django.db.models import QuerySet
from django_tenants.utils import get_tenant_model


def tenants_with_schema(schema_name: str) -> QuerySet:
    """The tenant owning ``schema_name``, as a queryset of at most one row.

    A queryset rather than an instance, so a caller after a related row can
    embed it as a subquery and keep its lookup to one query; ``.first()``
    gives the tenant itself. The tenant table lives in the public schema, which
    is on every tenant schema's search path, so this resolves from inside any
    tenant.
    """
    return get_tenant_model().objects.filter(schema_name=schema_name)
