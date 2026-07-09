"""Huey periodic tasks for the accounts app.

Two tasks live here:
  - ``alert_on_axes_bursts`` — surface brute-force fingerprints from
    django-axes (cross-tenant aggregation).
  - ``clear_expired_sessions`` — daily housekeeping; drops rows from
    ``django_session``.

See ``docs/todos/huey-to-do.txt`` for the full backlog.

Bootstrap reminder: nothing in this file runs until the ``HUEY`` config
block in ``config/settings.py`` is uncommented and a worker process
starts. Decorators register tasks at import time but the scheduler
needs to be alive to fire them.
"""

from __future__ import annotations

import datetime
import logging
from collections import Counter

from django.conf import settings
from django.core.mail import mail_admins
from django.core.management import call_command
from django.utils import timezone
from huey import crontab
from huey.contrib.djhuey import db_periodic_task

from apps.shared.tenants.sweep import for_each_tenant

log = logging.getLogger("django.security")
ops_log = logging.getLogger("tasks")

# Tunables — keep aligned with AXES_FAILURE_LIMIT in settings.py so the
# alert threshold matches what actually triggers a lockout.
BURST_THRESHOLD = getattr(settings, "AXES_FAILURE_LIMIT", 5)
BURST_WINDOW = datetime.timedelta(hours=1)

# Cooldown to avoid re-emailing about the same IP every 15 min while the
# burst is still inside the rolling window. The dedup state is in-process
# memory only — worker restarts reset it, which is fine: better an
# occasional duplicate alert than missed ones.
_ALERT_COOLDOWN = datetime.timedelta(hours=1)
_last_alerted: dict[str, datetime.datetime] = {}


@db_periodic_task(crontab(minute="*/15"), retries=2, retry_delay=300)
def alert_on_axes_bursts() -> None:
    """Surface brute-force fingerprints from django-axes.

    Aggregates ``AccessAttempt`` rows across every tenant schema over
    the last hour, groups by source IP, and alerts on any IP that hit
    the ``AXES_FAILURE_LIMIT`` threshold. The signal is a structured
    ``axes.burst`` line to ``security.log`` plus an ops email via
    ``ADMINS``.

    Cross-tenant aggregation matters here: a botnet that distributes 4
    attempts across each of 10 tenants from a single IP is more
    interesting than 5 attempts at one tenant. The per-tenant lockout
    (django-axes) already handles single-tenant bursts at request time;
    this task catches the slow / distributed pattern that lockout
    alone wouldn't surface.
    """
    # Resolve the axes model lazily — keeps the module importable even
    # if axes isn't fully initialised at decorator-time.
    from axes.models import AccessAttempt

    cutoff = timezone.now() - BURST_WINDOW
    by_ip: Counter[str] = Counter()

    def aggregate(tenant) -> None:
        # django-axes upserts one row per (username, ip, user_agent)
        # and increments ``failures_since_start`` per failure — so
        # we sum that field, not count rows.
        rows = (
            AccessAttempt.objects.filter(attempt_time__gte=cutoff)
            .exclude(ip_address__isnull=True)
            .values_list("ip_address", "failures_since_start")
            .iterator()
        )
        for ip, failures in rows:
            by_ip[str(ip)] += failures

    # Missing data from one bad tenant is better than no alert for any tenant,
    # so failures are isolated (and routed to the security log).
    for_each_tenant(aggregate, label="axes.burst", logger=log)

    now = timezone.now()
    fresh_bursts: list[tuple[str, int]] = []
    for ip, count in by_ip.items():
        if count < BURST_THRESHOLD:
            continue
        last = _last_alerted.get(ip)
        if last is not None and now - last < _ALERT_COOLDOWN:
            continue
        fresh_bursts.append((ip, count))
        _last_alerted[ip] = now

    for ip, count in fresh_bursts:
        log.warning(
            "axes.burst ip=%s count=%s window_hours=%s threshold=%s",
            ip,
            count,
            int(BURST_WINDOW.total_seconds() // 3600),
            BURST_THRESHOLD,
        )

    if fresh_bursts:
        _send_ops_alert(fresh_bursts)


def _send_ops_alert(bursts: list[tuple[str, int]]) -> None:
    """Email ``settings.ADMINS`` about the bursts.

    Uses ``mail_admins`` (Django built-in) rather than the per-tenant
    ``EmailService`` because this is platform-ops mail, not customer
    correspondence, and ``ADMINS`` is already configured for exactly
    this use case.
    """
    subject = f"[Jasmin] {len(bursts)} brute-force burst(s) detected"
    body_lines = [
        f"Window: last {int(BURST_WINDOW.total_seconds() // 3600)}h, "
        f"threshold >={BURST_THRESHOLD} failed-login attempts per IP "
        f"(aggregated across all tenants).",
        "",
        "IP                            count",
        "-" * 40,
    ]
    for ip, count in sorted(bursts, key=lambda x: -x[1]):
        body_lines.append(f"{ip:<30}{count:>10}")
    body_lines.extend(
        [
            "",
            "See logs/security.log -> grep 'axes.burst' for the structured "
            "log lines (one per IP).",
        ]
    )
    # fail_silently=True so a broken email backend doesn't crash the
    # scheduled task; the structured log line already captured the
    # signal regardless.
    mail_admins(subject, "\n".join(body_lines), fail_silently=True)


@db_periodic_task(crontab(hour="2", minute="30"), retries=2, retry_delay=300)
def clear_expired_sessions() -> None:
    """Drop expired rows from ``django_session``.

    ``django.contrib.sessions`` is in SHARED_APPS, so the session table
    lives in the public schema. ``clearsessions`` is Django's built-in
    command — it just runs ``Session.objects.filter(expire_date__lt=now).delete()``
    against the default schema, which is what we want.
    """
    call_command("clearsessions", verbosity=0)
    ops_log.info("housekeeping.sessions_cleared")
