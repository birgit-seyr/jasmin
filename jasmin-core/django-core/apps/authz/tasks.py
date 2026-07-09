"""Huey periodic tasks for the authz app.

Currently a single task: ``flush_expired_jwt_tokens``. See
``docs/todos/huey-to-do.txt`` for the full backlog.

Bootstrap reminder: nothing in this file runs until the ``HUEY`` config
block in ``config/settings.py`` is uncommented and a worker process
starts.
"""

from __future__ import annotations

import logging

from django.core.management import call_command
from huey import crontab
from huey.contrib.djhuey import db_periodic_task

from apps.shared.tenants.sweep import for_each_tenant

log = logging.getLogger("tasks")


@db_periodic_task(crontab(hour="2", minute="45"), retries=2, retry_delay=300)
def flush_expired_jwt_tokens() -> None:
    """Drop expired refresh-token rows per tenant schema.

    ``rest_framework_simplejwt.token_blacklist`` is in TENANT_APPS, so
    the ``OutstandingToken`` / ``BlacklistedToken`` tables live in each
    tenant schema. ``flushexpiredtokens`` is the built-in Simple JWT
    management command — it deletes outstanding tokens whose ``expires_at``
    is in the past (which cascades the blacklist rows).
    """

    def flush(tenant) -> None:
        call_command("flushexpiredtokens", verbosity=0)

    # Per-tenant isolation: a single bad tenant must NOT prevent the flush from
    # running on every other tenant. ``include_inactive=True`` keeps the
    # pre-adoption behaviour of flushing every non-public tenant — a frozen
    # tenant's blacklist tables still accumulate expired rows worth pruning.
    for_each_tenant(
        flush,
        label="housekeeping.jwt_blacklist_flushed",
        logger=log,
        include_inactive=True,
    )
    log.info("housekeeping.jwt_blacklist_flushed")
