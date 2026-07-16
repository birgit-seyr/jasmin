"""Fire every Huey periodic task synchronously, once, for dev/QA.

The scheduled tasks are normally fired by the ``huey`` consumer process
(see docker-compose.yml). In dev you don't want to wait until 02:30 or
crontab(minute="*/15") just to know if a new task works — this command
lets you trigger them all on demand.

Each task is invoked via Huey's ``call_local()`` helper, which runs the
underlying function in-process with full Django app context. No worker
needed, no Redis broker hit, no scheduler poke.

Usage::

    poetry run python manage.py run_periodic_tasks_now
    poetry run python manage.py run_periodic_tasks_now --only=alert_on_axes_bursts
    poetry run python manage.py run_periodic_tasks_now --skip=cleanup_stale_email_logs

Output: one line per task with ``[ok]``/``[FAIL]``, the elapsed time,
and — if the task returns a dict — its key=value summary appended.
Tasks that return ``None`` (most legacy tasks) just show the status
+ elapsed. Errors are caught per-task so one failing task doesn't
abort the rest; the traceback is printed and execution continues.

Convention for new task summaries: return a flat ``dict[str, int]`` of
the observations you'd want a dev/auditor to see at a glance — e.g.
``{"tenants_scanned": 1, "fresh_alerts": 0}``. Keep values primitive
so the formatter doesn't need special handling.
"""

from __future__ import annotations

import time
import traceback
from importlib import import_module
from typing import Any

from django.core.management.base import BaseCommand

# Module-path : list of task callables to invoke. New periodic tasks
# should be registered here so this command can find + run them.
# ``test_periodic_task_registry_complete`` fails the build if a
# ``@db_periodic_task`` / ``@periodic_task`` is added without registering it
# here (or allow-listing it in _INFRA_ONLY_PERIODIC_TASKS), so this can't drift.
TASK_REGISTRY: dict[str, list[str]] = {
    "apps.accounts.tasks": [
        "alert_on_axes_bursts",
        "clear_expired_sessions",
    ],
    "apps.authz.tasks": [
        "flush_expired_jwt_tokens",
    ],
    "apps.notifications.tasks": [
        "cleanup_stale_email_logs",
        "reconcile_stale_background_jobs",
        "prune_old_background_jobs",
    ],
    "apps.commissioning.tasks": [
        "nightly_invoice_hash_check",
        "cleanup_stale_import_batches",
        "cleanup_expired_capacity_reservations",
        "daily_subscription_renewals",
        "expire_stale_waiting_list_offers",
    ],
    "apps.shared.tenants.tasks": [
        "weekly_tenant_health_report",
        "prune_old_backups",
        "prune_old_action_rate_log",
    ],
    "apps.shared.super_admin.tasks": [
        "email_overdue_ops_items",
    ],
    "apps.shared.support.tasks": [
        "prune_orphan_support_tickets_task",
    ],
    "apps.gdpr.tasks": [
        "anonymise_long_cancelled_members",
        "alert_on_mass_deletes",
        "alert_on_deletion_endpoint_bursts",
    ],
}

# Periodic tasks that are pure infra (not business jobs a dev/QA run should
# "exercise") and are therefore intentionally NOT in TASK_REGISTRY. The
# registry-completeness test excludes exactly these.
_INFRA_ONLY_PERIODIC_TASKS: frozenset[str] = frozenset({"huey_heartbeat"})


def _format_summary(result: Any) -> str:
    """Render a task's return value as a ``key=value key=value`` string.

    Tasks that return ``None`` (most legacy tasks) yield ``""`` —
    caller appends nothing to the status line. Anything that isn't a
    ``dict`` falls back to ``repr(result)`` for visibility; this
    branch shouldn't fire under the documented convention but keeps
    the formatter total in case a task evolves and returns a list /
    namedtuple / dataclass before this helper is updated.
    """
    if result is None:
        return ""
    if isinstance(result, dict):
        return " ".join(f"{k}={v}" for k, v in result.items())
    return repr(result)


class Command(BaseCommand):
    help = "Run every Huey periodic task synchronously, once. Dev-only."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--only",
            action="append",
            default=None,
            help=(
                "Only run task(s) with the given name (without the module "
                "prefix). Can be given multiple times. Mutually exclusive "
                "with --skip."
            ),
        )
        parser.add_argument(
            "--skip",
            action="append",
            default=None,
            help=(
                "Skip task(s) with the given name. Can be given multiple "
                "times. Mutually exclusive with --only."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        only = set(options.get("only") or [])
        skip = set(options.get("skip") or [])
        if only and skip:
            self.stderr.write(
                self.style.ERROR("--only and --skip are mutually exclusive")
            )
            return

        ran = 0
        failed = 0
        for module_path, task_names in TASK_REGISTRY.items():
            try:
                module = import_module(module_path)
            except (ImportError, AttributeError) as exc:
                self.stderr.write(
                    self.style.ERROR(f"Could not import {module_path}: {exc}")
                )
                failed += 1
                continue

            for name in task_names:
                if only and name not in only:
                    continue
                if name in skip:
                    self.stdout.write(f"  [skip] {module_path}.{name}")
                    continue

                task = getattr(module, name, None)
                if task is None:
                    self.stderr.write(
                        self.style.ERROR(f"  [miss] {module_path}.{name} not found")
                    )
                    failed += 1
                    continue

                started = time.monotonic()
                try:
                    # ``call_local()`` is Huey's in-process invocation —
                    # runs the underlying function directly with full
                    # Django context. No worker, no broker.
                    result = task.call_local()
                except Exception:
                    elapsed_ms = int((time.monotonic() - started) * 1000)
                    self.stderr.write(
                        self.style.ERROR(
                            f"  [FAIL] {module_path}.{name} " f"({elapsed_ms} ms)"
                        )
                    )
                    self.stderr.write(traceback.format_exc())
                    failed += 1
                    continue

                elapsed_ms = int((time.monotonic() - started) * 1000)
                summary = _format_summary(result)
                line = f"  [ok]   {module_path}.{name} ({elapsed_ms} ms)"
                if summary:
                    line += f"  → {summary}"
                self.stdout.write(self.style.SUCCESS(line))
                ran += 1

        self.stdout.write("")
        summary = f"Ran {ran} task(s); {failed} failed."
        if failed:
            self.stdout.write(self.style.ERROR(summary))
        else:
            self.stdout.write(self.style.SUCCESS(summary))
