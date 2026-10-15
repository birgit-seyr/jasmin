"""Per-tenant sweep helper for periodic background tasks.

Every nightly/weekly housekeeping task repeats the same shape: iterate every
non-public tenant, enter its schema, do the work, and isolate failures so one
bad tenant never aborts the sweep across the others. :func:`for_each_tenant`
captures that loop once.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable

from django_tenants.utils import schema_context

from apps.shared.ops_alerts import alert_operator

from .models import Tenant

# Named apart from the ``logger`` parameter below so the caller-facing keyword
# matches the ``logger=`` spelling the other apps.shared helpers take.
_TASKS_LOGGER = logging.getLogger("tasks")

# One operator email per sweep and set of failed tenants within this window:
# some sweeps run every few minutes, and one that keeps failing the same way
# must not flood the inbox, while a nightly sweep that fails again the next
# night, or another tenant starting to fail, still sends.
SWEEP_FAILURE_ALERT_SECONDS = 20 * 3600


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
    sweep still runs for every other tenant. Once the sweep is done, the
    operator gets one email naming the failed tenants, since nobody watches the
    log: at most one per label and set of failed tenants every
    ``SWEEP_FAILURE_ALERT_SECONDS``. The sweep never re-raises: a Huey retry
    would run every tenant again, the ones that succeeded and already sent their
    mail included. Returns the number of tenants where ``work`` raised.

    A deactivated tenant is a frozen tenant (offboarding / non-payment / breach),
    so server-initiated sweeps skip it by default. Pass ``include_inactive=True``
    to opt a specific sweep back in (e.g. forensic tamper checks on a frozen
    tenant) — make that a visible, deliberate choice at the call site.

    ``label`` sets the failure-log prefix (keep the per-task string so log
    greps stay stable); ``logger`` redirects the failure log away from the
    module's ``"tasks"`` logger (pass the security logger for audit sweeps).
    """
    log = logger or _TASKS_LOGGER
    failed: list[str] = []
    failed_schemas: list[str] = []
    qs = Tenant.objects.exclude(schema_name="public")
    if not include_inactive:
        qs = qs.filter(is_active=True)
    for tenant in qs.iterator():
        try:
            with schema_context(tenant.schema_name):
                work(tenant)
        except Exception as exc:
            log.exception("%s.tenant_failed tenant=%s", label, tenant.schema_name)
            # The exception's class only: its message can carry row values.
            failed.append(f"{tenant.schema_name} ({type(exc).__name__})")
            failed_schemas.append(tenant.schema_name)
    if failed:
        # Hashed, so the cache key stays short however many tenants fail.
        failed_set = hashlib.sha256(
            ",".join(sorted(failed_schemas)).encode()
        ).hexdigest()[:16]
        alert_operator(
            f"{label}: {len(failed)} tenant(s) failed",
            f"The {label} sweep raised an error for: {', '.join(failed)}.\n\n"
            "Every other tenant ran normally, and the next scheduled run tries "
            "the failed ones again. The log of the process that ran the sweep "
            "(normally the huey container: docker compose logs huey) holds each "
            f"traceback as {label}.tenant_failed. A tenant being created at that "
            "moment can fail once while its schema is still migrating; that "
            "needs nothing unless it repeats.",
            throttle_key=f"sweep.tenant_failed:{label}:{failed_set}",
            throttle_seconds=SWEEP_FAILURE_ALERT_SECONDS,
        )
    return len(failed)
