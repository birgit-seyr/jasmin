"""Public tenant-URL / tenant-name resolution helpers.

Every tenant-facing email flow (invitations, password reset, GDPR deletion,
member notifications) needs two things off the current tenant: the base URL of
its React frontend (to build accept/reset/review links) and its human-readable
name (for the email greeting/footer). Both derive from ``connection.tenant``.

This module is the single public home for both, in the always-shared layer,
so any app — including ``apps.commissioning`` under the one-way isolation
rule — can import them.
"""

from __future__ import annotations

from typing import Any


def frontend_base_url(tenant: Any = None) -> str:
    """Base URL of the React frontend for ``tenant`` (default: the current one).

    Built from the tenant's primary domain, or any of its domains when none is
    primary. Under ``schema_context`` — Huey tasks, management commands — the
    tenant is a ``FakeTenant`` carrying only ``schema_name``, so its domains are
    looked up by schema name. ``FRONTEND_BASE_URL`` is the last fallback, for a
    tenant without any domain row.

    Not cached: the lookup is one indexed query per link, links are built per
    email, and a per-process cache would keep serving a domain the super-admin
    has since changed until the worker restarts.
    """
    from django.conf import settings

    domain = _primary_domain(tenant)
    if domain:
        scheme = "http" if settings.DEBUG else "https"
        return f"{scheme}://{domain}"
    return settings.FRONTEND_BASE_URL


def _primary_domain(tenant: Any) -> str | None:
    from django_tenants.utils import get_tenant_domain_model

    from apps.shared.tenant_lookup import tenants_with_schema
    from core.tenant_db import connection

    if tenant is None:
        tenant = connection.tenant
    domains = getattr(tenant, "domains", None)
    if domains is None:
        schema_name = getattr(tenant, "schema_name", None)
        if not schema_name:
            return None
        # The domain table lives in the public schema, which is on every tenant
        # schema's search path, so this resolves from inside any tenant.
        domains = get_tenant_domain_model().objects.filter(
            tenant__in=tenants_with_schema(schema_name)
        )
    return (
        domains.order_by("-is_primary", "pk").values_list("domain", flat=True).first()
    )


def tenant_name() -> str:
    """Human-readable name of the current tenant, or ``""`` when unresolved."""
    from core.tenant_db import connection

    return getattr(connection.tenant, "name", "")
