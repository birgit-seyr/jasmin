"""Support-app operations (function-only, no Service class → plain name)."""

from __future__ import annotations

import logging

log = logging.getLogger("tasks")


def prune_orphan_support_tickets() -> int:
    """Delete tickets whose tenant no longer exists.

    ``SupportTicket`` lives in the public schema with no FK to ``Tenant`` (see
    the model docstring), so a torn-down tenant (``auto_drop_schema``) leaves
    orphan rows with no cascade. This reaps them (messages cascade via the
    intra-app FK). Returns the number of tickets removed.
    """
    from apps.shared.tenants.models import Tenant

    from .models import SupportTicket

    live = set(Tenant.objects.values_list("schema_name", flat=True))
    # Guard the empty-``__in`` footgun: ``exclude(tenant_schema__in=set())``
    # matches EVERY row, which in a nightly unattended delete would wipe the
    # table. An empty tenant set means something is wrong, not "all orphaned".
    if not live:
        log.warning("support_ticket.prune_orphans.skipped no live tenants found")
        return 0
    orphans = SupportTicket.objects.exclude(tenant_schema__in=live)
    deleted, _ = orphans.delete()
    log.info("support_ticket.prune_orphans.done deleted=%s", deleted)
    return deleted
