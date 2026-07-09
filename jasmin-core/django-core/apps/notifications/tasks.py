"""Huey periodic tasks for the notifications app.

Housekeeping tasks: ``cleanup_stale_email_logs`` (EmailLog retention pruning),
``reconcile_stale_background_jobs`` (marks worker-lost jobs failed + alerts),
``prune_old_background_jobs`` (BackgroundJob retention pruning), and
``huey_heartbeat`` (liveness signal for the consumer's Docker healthcheck).

Bootstrap reminder: nothing in this file runs until the ``HUEY`` config
block in ``config/settings.py`` is uncommented and a worker process
starts.
"""

from __future__ import annotations

import datetime
import logging
import os
import time

from django.core.mail import mail_admins
from django.db.models import Q
from django.utils import timezone
from huey import crontab
from huey.contrib.djhuey import db_periodic_task, periodic_task

from apps.shared.tenants.sweep import for_each_tenant

log = logging.getLogger("tasks")

# 90 days is the operational sweet spot: long enough to debug a
# "did this member get the invoice?" question, short enough not to
# bloat the per-tenant table.
RETENTION_DAYS = 90

# EmailLog statuses we DELETE after the retention window. Statuses we
# KEEP regardless of age (because they're still actionable from an ops
# / forensic angle) are everything else, i.e. ``pending`` (still in
# flight), ``deferred`` (provider will retry), ``failed`` (network /
# unknown error worth investigating), ``rejected`` (permanent config
# issue worth keeping until fixed), ``complained`` (recipient marked
# as spam — kept for the suppression-list audit trail).
DELETABLE_STATUSES = ("sent", "delivered", "bounced")


@db_periodic_task(crontab(hour="2", minute="15"), retries=2, retry_delay=300)
def cleanup_stale_email_logs() -> None:
    """Prune the per-tenant ``EmailLog`` table.

    EmailLog grows linearly with sends. Iterate every tenant schema and
    delete rows older than ``RETENTION_DAYS`` whose status is in the
    deletable set (the bulk of healthy traffic). Anything still in
    flight or in a state ops might want to inspect is kept.
    """
    # Imported lazily because ``EmailLog`` lives in a TENANT_APP — the
    # decorator runs at module-load time in any schema, but the actual
    # query only runs once we've entered a tenant via schema_context.
    from apps.notifications.models import EmailLog

    cutoff = timezone.now() - datetime.timedelta(days=RETENTION_DAYS)
    counters = {"deleted": 0}

    def prune(tenant) -> None:
        deleted, _ = EmailLog.objects.filter(
            created_at__lt=cutoff,
            status__in=DELETABLE_STATUSES,
        ).delete()
        counters["deleted"] += deleted
        if deleted:
            log.info(
                "housekeeping.email_log_pruned tenant=%s deleted=%s",
                tenant.schema_name,
                deleted,
            )

    for_each_tenant(prune, label="housekeeping.email_log_pruned", logger=log)

    log.info(
        "housekeeping.email_log_pruned total_deleted=%s retention_days=%s",
        counters["deleted"],
        RETENTION_DAYS,
    )


# A live bulk task heartbeats per item (offer / invoice-reminder sends call
# update_progress after every recipient), so heartbeat_at advances every few
# seconds while a worker is alive. A heartbeat this stale therefore means the
# worker crashed / was OOM-killed / hung — or, for a still-queued row, that the
# on_commit Redis dispatch never landed. One hour is far beyond any healthy
# bulk-send runtime, so the sweep never false-fails a genuinely running job.
STALE_JOB_TIMEOUT = datetime.timedelta(hours=1)


@db_periodic_task(crontab(minute="*/15"), retries=2, retry_delay=300)
def reconcile_stale_background_jobs() -> None:
    """Mark worker-lost ``BackgroundJob`` rows failed.

    A SIGKILL/OOM of the Huey worker mid-task runs neither ``mark_done`` nor
    ``mark_failed`` (Huey's Redis pop has no ack/redelivery and the bulk tasks
    are ``retries=0``), so the row is stranded at ``running`` forever with a
    frozen progress snapshot — the office's polling drawer shows an eternal
    in-flight job. Symmetrically a ``queued`` row whose ``on_commit`` Redis
    dispatch failed has no consumer. Sweep both: any queued/running row whose
    last liveness signal (``heartbeat_at``, falling back to ``created_at`` for a
    never-started queued row) predates the timeout is marked failed so the
    frontend poll terminates and the operator sees the crash.
    """
    from apps.notifications.models import BackgroundJob

    cutoff = timezone.now() - STALE_JOB_TIMEOUT
    # Coalesce(heartbeat_at, created_at) < cutoff, spelled as a Q so it can drive
    # a plain .update() (an annotate()+update() on the same queryset is brittle).
    stale = Q(heartbeat_at__isnull=False, heartbeat_at__lt=cutoff) | Q(
        heartbeat_at__isnull=True, created_at__lt=cutoff
    )
    counters = {"reconciled": 0}
    reconciled_by_tenant: list[tuple[str, int]] = []

    def reconcile(tenant) -> None:
        reconciled = BackgroundJob.objects.filter(
            stale,
            status__in=(
                BackgroundJob.STATUS_QUEUED,
                BackgroundJob.STATUS_RUNNING,
            ),
        ).update(
            status=BackgroundJob.STATUS_FAILED,
            error="worker lost — no heartbeat within timeout",
            completed_at=timezone.now(),
        )
        counters["reconciled"] += reconciled
        if reconciled:
            reconciled_by_tenant.append((tenant.schema_name, reconciled))
            log.warning(
                "housekeeping.background_job_reconciled tenant=%s failed=%s",
                tenant.schema_name,
                reconciled,
            )

    for_each_tenant(
        reconcile, label="housekeeping.background_job_reconciled", logger=log
    )

    total_reconciled = counters["reconciled"]
    log.info(
        "housekeeping.background_job_reconciled total_failed=%s timeout=%s",
        total_reconciled,
        STALE_JOB_TIMEOUT,
    )

    # A reconciled job = a background task the worker lost (OOM / crash / hung
    # consumer, or a queued row whose dispatch never landed). Alert admins so a
    # silently-dead consumer surfaces without someone watching logs. No spam:
    # each stranded row is flipped to failed exactly once, so it's only counted
    # in the run that first detects it. Mirrors the mail_admins alert pattern in
    # gdpr/accounts tasks; a mail failure must not fail the sweep.
    if reconciled_by_tenant:
        detail = "\n".join(
            f"  {schema}: {count}" for schema, count in reconciled_by_tenant
        )
        try:
            mail_admins(
                subject=f"[Jasmin] {total_reconciled} background job(s) marked worker-lost",
                message=(
                    "The background-job watchdog marked these queued/running "
                    "BackgroundJob rows failed after "
                    f"{STALE_JOB_TIMEOUT} without a heartbeat — the Huey consumer "
                    "likely crashed, was OOM-killed, or wedged.\n\n"
                    f"Per tenant:\n{detail}\n\n"
                    "Check the huey container and logs/app.log."
                ),
            )
        except Exception:
            log.exception("housekeeping.background_job_reconciled.alert_failed")


@db_periodic_task(crontab(hour="2", minute="20"), retries=2, retry_delay=300)
def prune_old_background_jobs() -> None:
    """Prune terminal (done/failed) ``BackgroundJob`` rows past the retention window.

    BackgroundJob was the one growing operational table with no retention sweep:
    each bulk send leaves a row whose ``result`` JSON carries per-reseller names
    and outcomes that outlived the EmailLog retention window forever. Delete
    done/failed rows older than ``RETENTION_DAYS`` (mirrors the EmailLog policy);
    queued/running rows are never touched here — the reconcile watchdog owns
    those.
    """
    from apps.notifications.models import BackgroundJob

    cutoff = timezone.now() - datetime.timedelta(days=RETENTION_DAYS)
    counters = {"deleted": 0}

    def prune(tenant) -> None:
        deleted, _ = BackgroundJob.objects.filter(
            status__in=(
                BackgroundJob.STATUS_DONE,
                BackgroundJob.STATUS_FAILED,
            ),
            created_at__lt=cutoff,
        ).delete()
        counters["deleted"] += deleted
        if deleted:
            log.info(
                "housekeeping.background_job_pruned tenant=%s deleted=%s",
                tenant.schema_name,
                deleted,
            )

    for_each_tenant(prune, label="housekeeping.background_job_pruned", logger=log)

    log.info(
        "housekeeping.background_job_pruned total_deleted=%s retention_days=%s",
        counters["deleted"],
        RETENTION_DAYS,
    )


# Liveness heartbeat for the Huey container's Docker healthcheck. The consumer
# rewrites HUEY_HEARTBEAT_FILE every minute; the compose healthcheck fails the
# container when the file is missing or stale (all workers wedged / scheduler
# dead), so orchestration restarts a consumer that "looks up" but runs nothing.
# ``periodic_task`` (no DB) on purpose: a DB hiccup must not mask a live
# consumer — DB liveness is the backend container's /health/ concern. This is
# infra, not a business job, so it is intentionally NOT in run_periodic_tasks_now.
_HEARTBEAT_FILE = os.environ.get("HUEY_HEARTBEAT_FILE", "/tmp/huey_heartbeat")


@periodic_task(crontab(minute="*"))
def huey_heartbeat() -> None:
    """Touch the heartbeat file so the container healthcheck sees a live consumer."""
    try:
        with open(_HEARTBEAT_FILE, "w") as handle:
            handle.write(str(int(time.time())))
    except OSError:
        log.exception(
            "housekeeping.huey_heartbeat.write_failed path=%s", _HEARTBEAT_FILE
        )
