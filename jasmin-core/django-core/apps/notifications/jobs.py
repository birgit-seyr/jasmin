"""Helpers for enqueueing and progress-reporting ``BackgroundJob`` rows.

Every Huey-backed view follows the same shape: create a job row,
schedule the task once the surrounding transaction commits, return
the job id. The task then progresses the row to ``running`` / ``done``
/ ``failed`` and writes ``progress`` snapshots in flight.

These helpers keep that boilerplate in one place so individual views
and tasks stay thin.

Multi-tenancy: tasks run in a Huey worker, OUTSIDE any HTTP request
and therefore OUTSIDE a tenant schema context. The enqueue helper
captures ``connection.tenant.schema_name`` at the call site and
passes it into the task; the task wraps its body in
``schema_context(schema_name)`` before touching any tenant model.
This matches the pattern in ``apps/commissioning/tasks.py``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

from django.db import connection, transaction
from django.utils import timezone
from django_tenants.utils import schema_context

from .models import BackgroundJob

logger = logging.getLogger(__name__)
# Background-job task failures are logged here. Use the "tasks" logger (which
# settings.LOGGING wires to the app_file handler) rather than this module's
# __name__ logger, which isn't configured and would propagate to root — i.e.
# the failure traceback would miss logs/app.log. This matches where the task
# bodies logged their failures before run_job centralized the lifecycle.
_task_logger = logging.getLogger("tasks")


def enqueue_job(
    *,
    kind: str,
    task: Callable[..., Any],
    task_kwargs: dict[str, Any],
    created_by=None,
) -> BackgroundJob:
    """Create a ``queued`` ``BackgroundJob`` row + schedule ``task``.

    ``task`` is a Huey-decorated callable (``@db_task`` etc.) that
    accepts ``schema_name`` and ``job_id`` as its first two named
    arguments plus whatever ``task_kwargs`` the caller provides.

    The Huey call is registered via ``transaction.on_commit`` so a
    rolled-back request never leaves a phantom queued job — the
    worker would otherwise pick it up and fail with ``DoesNotExist``.

    Caller MUST be inside a tenant schema (the standard HTTP request
    case). For management commands or non-HTTP entrypoints, set
    ``connection.tenant`` explicitly or fall back to
    ``schema_context`` around this call.
    """
    schema_name = _current_schema_name()
    job = BackgroundJob.objects.create(
        kind=kind,
        status=BackgroundJob.STATUS_QUEUED,
        created_by=created_by,
    )
    transaction.on_commit(
        lambda: task(schema_name=schema_name, job_id=str(job.id), **task_kwargs)
    )
    logger.info(
        "background_job.enqueued kind=%s job_id=%s schema=%s",
        kind,
        job.id,
        schema_name,
    )
    return job


def _current_schema_name() -> str:
    tenant = getattr(connection, "tenant", None)
    name = getattr(tenant, "schema_name", None)
    if not name:
        raise RuntimeError(
            "enqueue_job called outside a tenant schema — "
            "wrap the caller in schema_context()."
        )
    return name


def mark_running(job_id: str) -> None:
    """Flip a queued job to ``running``. Idempotent.

    Stamps ``heartbeat_at`` — the first sign of worker liveness, and the
    baseline the stale-job reconciliation measures against until the first
    progress tick.
    """
    BackgroundJob.objects.filter(pk=job_id).update(
        status=BackgroundJob.STATUS_RUNNING,
        heartbeat_at=timezone.now(),
    )


def update_progress(job_id: str, progress: dict[str, Any]) -> None:
    """Overwrite the ``progress`` JSON blob for an in-flight job.

    Called periodically from the task body to drive the polling
    drawer's progress bar. We intentionally do a full overwrite rather
    than a merge — keeps the contract simple and avoids stale keys
    sticking around when a task changes its progress shape.

    Also refreshes ``heartbeat_at`` so a live task (which ticks per item)
    keeps proving liveness to the stale-job reconciliation sweep.
    """
    BackgroundJob.objects.filter(pk=job_id).update(
        progress=progress,
        heartbeat_at=timezone.now(),
    )


def mark_done(job_id: str, result: dict[str, Any] | None) -> None:
    # EML-8: BackgroundJob.result is JSONField(default=dict) with NO null=True, so
    # a task body that completes without setting handle.result (left as None)
    # would write SQL NULL → IntegrityError, flipping a SUCCEEDED job to 'failed'.
    # Coerce to the field's own default.
    BackgroundJob.objects.filter(pk=job_id).update(
        status=BackgroundJob.STATUS_DONE,
        result=result if result is not None else {},
        completed_at=timezone.now(),
    )


def mark_failed(job_id: str, error: str) -> None:
    BackgroundJob.objects.filter(pk=job_id).update(
        status=BackgroundJob.STATUS_FAILED,
        # Cap at 2000 chars for parity with EmailLog.error — long
        # stack traces belong in the log, not in a polled API
        # response.
        error=str(error)[:2000],
        completed_at=timezone.now(),
    )


class _JobHandle:
    """Mutable handle yielded by :func:`run_job`. Set ``result`` to the dict
    the job should persist on success; ``progress`` is a ready-made callback
    to pass as a service's ``progress_cb=``."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self.result: dict[str, Any] | None = None

    def progress(self, snapshot: dict[str, Any]) -> None:
        update_progress(self.job_id, snapshot)


@contextmanager
def run_job(schema_name: str, job_id: str):
    """Wrap a ``BackgroundJob`` task body with its lifecycle scaffolding.

    Enters the tenant schema, flips the job to ``running``, and on clean exit
    flips it to ``done`` with whatever the body recorded on ``handle.result``.
    On ANY exception it logs the traceback and flips the job to ``failed`` —
    the exception is deliberately swallowed so Huey doesn't retry (a retry on
    a half-finished SMTP blast is almost never what you want; the failure is
    surfaced to the office via the polled job row).

    Usage::

        with run_job(schema_name, job_id) as job:
            job.result = SomeService.do_work(progress_cb=job.progress)
    """
    handle = _JobHandle(job_id)
    with schema_context(schema_name):
        try:
            mark_running(job_id)
            yield handle
            mark_done(job_id, handle.result)
        except Exception as exc:
            _task_logger.exception(
                "background_job.failed schema=%s job=%s", schema_name, job_id
            )
            mark_failed(job_id, str(exc))
