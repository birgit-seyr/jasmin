"""Huey periodic tasks for the super_admin app.

Currently a single task: ``email_overdue_ops_items`` — weekly digest
of overdue ``OpsChecklistItem`` rows.

Bootstrap reminder: nothing in this file runs until the ``HUEY`` config
block in ``config/settings.py`` is uncommented and a worker process
starts. The decorator below registers the task at import time but the
scheduler needs to be alive to fire it.
"""

from __future__ import annotations

import logging

from django.core.mail import mail_admins
from huey import crontab
from huey.contrib.djhuey import db_periodic_task

log = logging.getLogger("tasks")


@db_periodic_task(
    crontab(day_of_week="1", hour="9", minute="0"), retries=2, retry_delay=300
)
def email_overdue_ops_items() -> None:
    """Weekly Monday-09:00 digest of overdue ops checklist items.

    Quiet when nothing's overdue — no email goes out unless there's
    actually something for you to do. ``fail_silently=True`` so a
    broken email backend doesn't crash the scheduled task; the
    structured log lines below still capture the data.
    """
    # Lazy import — keeps the module importable in environments where
    # the migrations haven't run yet (e.g. fresh test DB).
    from .models import OpsChecklistItem

    items = OpsChecklistItem.objects.filter(is_active=True).prefetch_related("runs")
    overdue = [item for item in items if item.is_overdue]
    if not overdue:
        log.info("ops.checklist.digest no_overdue")
        return

    body_lines = [
        f"{len(overdue)} operational checklist item(s) are overdue.",
        "",
    ]
    for item in overdue:
        last_run = item.last_run
        last_run_date = (
            last_run.completed_at.strftime("%Y-%m-%d") if last_run else "never"
        )
        body_lines.append(
            f"- {item.title}"
            f"\n    last run: {last_run_date}"
            f"\n    due:      {item.next_due_at:%Y-%m-%d}"
            f"\n    interval: every {item.interval_days} days"
            f"\n    runbook:  {item.description.splitlines()[0] if item.description else '-'}"
        )
        log.info(
            "ops.checklist.overdue kind=%s next_due=%s last_run=%s",
            item.kind,
            item.next_due_at.isoformat(),
            last_run_date,
        )
    body_lines.append("")
    body_lines.append("Mark items done in the SuperAdmin → Ops Checklist UI.")

    mail_admins(
        f"[Jasmin ops] {len(overdue)} checklist item(s) overdue",
        "\n".join(body_lines),
        fail_silently=True,
    )
