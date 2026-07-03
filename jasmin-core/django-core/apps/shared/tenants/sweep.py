"""Per-tenant sweep helper for periodic background tasks.

Every nightly/weekly housekeeping task repeats the same shape: iterate every
non-public tenant, enter its schema, do the work, and isolate failures so one
bad tenant never aborts the sweep across the others. :func:`for_each_tenant`
captures that loop once.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from django_tenants.utils import schema_context

from .models import Tenant

_default_logger = logging.getLogger("tasks")


def for_each_tenant(
    work: Callable[[Tenant], None],
    *,
    label: str = "for_each_tenant",
    logger: logging.Logger | None = None,
    include_inactive: bool = False,
) -> int:
    """Run ``work(tenant)`` for every ACTIVE non-public tenant, inside its schema.

    Failures are isolated: a tenant whose ``work`` raises is logged (with
    traceback, as ``"<label>.tenant_failed tenant=…"``) and skipped, so the
    sweep still runs for every other tenant. Returns the number of tenants
    where ``work`` raised.

    A deactivated tenant is a frozen tenant (offboarding / non-payment / breach),
    so server-initiated sweeps skip it by default. Pass ``include_inactive=True``
    to opt a specific sweep back in (e.g. forensic tamper checks on a frozen
    tenant) — make that a visible, deliberate choice at the call site.

    ``label`` sets the failure-log prefix (keep the per-task string so log
    greps stay stable); ``logger`` overrides the destination (defaults to the
    ``"tasks"`` logger — pass the security logger for audit sweeps).
    """
    log = logger or _default_logger
    failures = 0
    qs = Tenant.objects.exclude(schema_name="public")
    if not include_inactive:
        qs = qs.filter(is_active=True)
    for tenant in qs.iterator():
        try:
            with schema_context(tenant.schema_name):
                work(tenant)
        except Exception:
            log.exception("%s.tenant_failed tenant=%s", label, tenant.schema_name)
            failures += 1
    return failures
