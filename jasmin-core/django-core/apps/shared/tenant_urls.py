"""Public tenant-URL / tenant-name resolution helpers.

Every tenant-facing email flow (invitations, password reset, GDPR deletion,
member notifications) needs two things off the current tenant: the base URL of
its React frontend (to build accept/reset/review links) and its human-readable
name (for the email greeting/footer). Both derive from ``connection.tenant``.

These were previously private helpers (``_frontend_base_url`` / ``_tenant_name``)
inside ``apps.shared.invitations``, imported cross-app under their underscore
names — a load-bearing utility with a misleading home, and the base-URL logic
had already been re-inlined (and drifted) inside
``apps.shared.tenants.email_service.capture_tenant_email_context``. This module
is their single public home in the always-shared layer, so any app — including
``apps.commissioning`` under the one-way isolation rule — can import them.
"""

from __future__ import annotations


def frontend_base_url() -> str:
    """Best-effort base URL of the React frontend for the current tenant.

    Resolves the tenant's primary domain (falling back to any domain of the
    tenant); if none is available — management commands, tests, or a worker
    where ``connection.tenant`` is a ``FakeTenant`` without a ``domains``
    relation — falls back to the ``FRONTEND_BASE_URL`` setting.
    """
    from django.conf import settings
    from django.db import connection

    tenant = getattr(connection, "tenant", None)
    domains = getattr(tenant, "domains", None) if tenant is not None else None
    if domains is not None:
        try:
            domain_obj = domains.filter(is_primary=True).first() or domains.first()
        except (AttributeError, TypeError):
            domain_obj = None
        if domain_obj:
            scheme = "http" if settings.DEBUG else "https"
            return f"{scheme}://{domain_obj.domain}"
    return getattr(settings, "FRONTEND_BASE_URL", "http://localhost:3000")


def tenant_name() -> str:
    """Human-readable name of the current tenant, or ``""`` when unresolved."""
    from django.db import connection

    tenant = getattr(connection, "tenant", None)
    return getattr(tenant, "name", "") or ""
