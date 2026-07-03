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
from django_tenants.utils import schema_context
from huey import crontab
from huey.contrib.djhuey import db_periodic_task

from apps.shared.tenants.models import Tenant

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
    for tenant in Tenant.objects.exclude(schema_name="public").iterator():
        # Per-tenant try/except: a single bad tenant must NOT prevent
        # the flush from running on every other tenant.
        try:
            with schema_context(tenant.schema_name):
                call_command("flushexpiredtokens", verbosity=0)
        except Exception:
            log.exception(
                "housekeeping.jwt_blacklist_flushed.tenant_failed tenant=%s",
                tenant.schema_name,
            )
    log.info("housekeeping.jwt_blacklist_flushed")
