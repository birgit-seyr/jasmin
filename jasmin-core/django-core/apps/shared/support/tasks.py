"""Huey periodic tasks for the support app.

Bootstrap reminder: nothing here runs until the ``HUEY`` worker is up (mirrors
apps/shared/tenants/tasks.py).
"""

from __future__ import annotations

from huey import crontab
from huey.contrib.djhuey import db_periodic_task

from .services import prune_orphan_support_tickets


@db_periodic_task(crontab(hour="4", minute="45"), retries=2, retry_delay=600)
def prune_orphan_support_tickets_task() -> int:
    """Reap tickets left behind by torn-down tenants (public schema, no cascade)."""
    return prune_orphan_support_tickets()
