"""Huey periodic tasks for the tenants app.

Currently a single task: ``weekly_tenant_health_report``. See
``docs/todos/huey-to-do.txt`` for the full backlog.

Bootstrap reminder: nothing in this file runs until the ``HUEY`` config
block in ``config/settings.py`` is uncommented and a worker process
starts.
"""

from __future__ import annotations

import datetime
import logging
import re
from collections.abc import Iterable
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.mail import mail_admins
from django.utils import timezone
from django_tenants.utils import schema_context
from huey import crontab
from huey.contrib.djhuey import db_periodic_task

from apps.shared.tenants.sweep import for_each_tenant

log = logging.getLogger("tasks")

# (app_label, model_name, label) — tables we monitor weekly. Ordered
# roughly biggest-to-smallest expected growth so the report reads
# top-down. Add or remove entries as the schema evolves; missing models
# (e.g. an app not yet installed) are silently skipped.
MONITORED_TABLES: list[tuple[str, str, str]] = [
    ("commissioning", "Member", "Member"),
    ("commissioning", "Subscription", "Subscription"),
    ("commissioning", "ShareDelivery", "ShareDelivery"),
    ("payments", "ChargeSchedule", "ChargeSchedule"),
    ("notifications", "EmailLog", "EmailLog"),
    ("auditlog", "LogEntry", "auditlog_logentry"),
]


@db_periodic_task(
    crontab(hour="7", minute="0", day_of_week="1"), retries=2, retry_delay=300
)
def weekly_tenant_health_report() -> None:
    """Emit a weekly per-tenant row-count summary.

    Per tenant, counts rows on the ``MONITORED_TABLES`` and (a) logs
    one structured ``tenant.health.report`` line to ``app.log`` (one
    per tenant) and (b) accumulates a human-readable digest emailed
    once to ``settings.ADMINS``. Catches trend-monitoring failures
    ("auditlog is 50x last month's size") without a Prometheus stack.

    Counts are exact ``.count()`` calls — fine at small/medium tenant
    sizes. If a tenant ever crosses ~1M rows on auditlog, switch the
    auditlog row to the estimated-count trick (``pg_class.reltuples``)
    so the report stays sub-second.
    """
    sections: list[str] = []

    def collect(tenant) -> None:
        counts = _count_per_table(tenant.schema_name)
        if not counts:
            return
        sections.append(_format_section(tenant.schema_name, counts))
        # Structured log line — parseable by grep / Loki / log aggregator.
        kv = " ".join(f"{label}={n}" for label, n in counts.items())
        log.info("tenant.health.report tenant=%s %s", tenant.schema_name, kv)

    for_each_tenant(collect, label="tenant.health.report", logger=log)

    if not sections:
        return

    today = timezone.now().date().isoformat()
    subject = f"[Jasmin] weekly health digest — {today}"
    body = (
        f"Weekly row-count snapshot across {len(sections)} tenant(s).\n"
        f"Use this to spot table-growth anomalies week-over-week.\n\n"
        + "\n\n".join(sections)
    )
    # fail_silently=True so a broken email backend doesn't crash the
    # scheduled task; the structured log lines already captured the data.
    mail_admins(subject, body, fail_silently=True)


def _count_per_table(schema_name: str) -> dict[str, int]:
    """Return {label: row_count} for ``MONITORED_TABLES`` inside ``schema_name``."""
    counts: dict[str, int] = {}
    with schema_context(schema_name):
        for app_label, model_name, label in MONITORED_TABLES:
            try:
                Model = apps.get_model(app_label, model_name)
            except LookupError:
                # Model not installed in this build — skip silently.
                continue
            counts[label] = Model.objects.count()
    return counts


def _format_section(schema_name: str, counts: dict[str, int]) -> str:
    """Format the per-tenant block for the email body."""
    width = max((len(label) for label in counts), default=10)
    lines = [f"Schema: {schema_name}"]
    for label, n in counts.items():
        lines.append(f"  {label:<{width}}  {n:>10,}")
    return "\n".join(lines)


# ---------------------------------------------------------------
# Backup pruning (Grandfather-Father-Son retention)
# ---------------------------------------------------------------


_BACKUP_FILENAME_RE = re.compile(
    # ``jasmin_20260603_020000.sql.gz.gpg`` (DB dump) and
    # ``jasmin_media_20260603_020000.tar.gz.gpg`` (media archive) per
    # backups/backup.sh. ``kind`` keeps the two retained INDEPENDENTLY.
    r"^.+?_(?P<ts>\d{8}_\d{6})\.(?P<kind>sql|tar)\.gz\.gpg$"
)


def _backup_dir() -> Path:
    """Resolve where the backups live.

    Defaults to ``/backups`` (the path inside the prod container —
    same value the shell script in ``backups/backup.sh`` uses).
    Override via ``BACKUP_DIR`` in ``settings.py`` for dev / tests.
    """
    return Path(getattr(settings, "BACKUP_DIR", "/backups"))


def _parse_backup(name: str) -> tuple[datetime.datetime, str] | None:
    """Return ``(timestamp, kind)`` for a recognised backup filename, else None.

    ``kind`` is ``"sql"`` (DB dump) or ``"tar"`` (media archive). The two are
    retained INDEPENDENTLY so a weekly/monthly prune never drops the media
    archive just because a DB dump for the same period sorted first.
    """
    match = _BACKUP_FILENAME_RE.match(name)
    if match is None:
        return None
    try:
        ts = datetime.datetime.strptime(match.group("ts"), "%Y%m%d_%H%M%S")
    except ValueError:
        return None
    return ts, match.group("kind")


def _parse_timestamp(name: str) -> datetime.datetime | None:
    """Return the timestamp encoded in a backup filename, or None
    if the file doesn't match the naming convention."""
    parsed = _parse_backup(name)
    return parsed[0] if parsed else None


def classify_backups_for_pruning(
    paths: Iterable[Path], now: datetime.datetime
) -> tuple[list[Path], list[Path]]:
    """GFS classification of backup files into ``(keep, delete)``.

    Pure function — no filesystem mutation. Lets us drive the
    decision logic in tests without touching real disk.

    Retention rule (matches docs/retention-policy.md):

      * Daily tier (≤ 30 days old): keep every backup
      * Weekly tier (30–365 days old): keep the LATEST backup of
        each ISO week
      * Monthly tier (> 365 days old): keep the LATEST backup of
        each calendar month — kept forever (≥10y obligation per
        HGB §257 / AO §147)

    Files whose filename doesn't match the ``..._YYYYMMDD_HHMMSS.sql.gz.gpg``
    pattern are returned in ``keep`` — we don't delete what we
    can't identify.
    """
    parsed: list[tuple[Path, datetime.datetime, str]] = []
    keep: list[Path] = []
    for path in paths:
        info = _parse_backup(path.name)
        if info is None:
            keep.append(path)
            continue
        ts, kind = info
        parsed.append((path, ts, kind))

    daily_cutoff = now - datetime.timedelta(days=30)
    weekly_cutoff = now - datetime.timedelta(days=365)

    # Most-recent-first within each window so the "latest of group"
    # decision is a simple "first seen wins".
    parsed.sort(key=lambda item: item[1], reverse=True)

    delete: list[Path] = []
    # ``kind`` is part of every key so DB dumps and media archives are pruned as
    # two independent series (one latest-per-week / -per-month kept EACH).
    seen_week: set[tuple[str, int, int]] = set()
    seen_month: set[tuple[str, int, int]] = set()

    for path, ts, kind in parsed:
        if ts >= daily_cutoff:
            # Daily tier — keep every backup.
            keep.append(path)
            continue
        if ts >= weekly_cutoff:
            iso_year, iso_week, _ = ts.isocalendar()
            key = (kind, iso_year, iso_week)
            if key in seen_week:
                delete.append(path)
            else:
                seen_week.add(key)
                keep.append(path)
            continue
        # Monthly tier — kept forever, one per calendar month.
        key = (kind, ts.year, ts.month)
        if key in seen_month:
            delete.append(path)
        else:
            seen_month.add(key)
            keep.append(path)

    return keep, delete


@db_periodic_task(crontab(hour="5", minute="0"), retries=2, retry_delay=600)
def prune_old_backups() -> dict[str, int]:
    """Apply GFS retention to the pg_dump backups on disk.

    Runs daily at 05:00 (after the backup script's 02:00 dump and
    after the GDPR retention sweep at 03:00 + the housekeeping at
    02:30 — those are unrelated but tight scheduling minimises
    overlap with the daily traffic peak).

    The Huey container must have the backup volume mounted (see
    ``docker-compose.yml`` — the volume is shared with the backup
    container's ``./backups:/backups`` mount). Without that, the
    task logs an INFO line and returns zeros — it's a no-op, not
    an error.

    Returns ``{"kept": N, "deleted": M, "unrecognised": K}`` for
    the dev/QA runner.
    """
    backup_dir = _backup_dir()
    if not backup_dir.exists():
        log.info(
            "backup.prune.no_dir dir=%s — task is a no-op; check the "
            "huey container's volume mount.",
            backup_dir,
        )
        return {"kept": 0, "deleted": 0, "unrecognised": 0}

    files = [p for p in backup_dir.iterdir() if p.is_file()]
    unrecognised = sum(1 for p in files if _parse_timestamp(p.name) is None)
    keep, delete = classify_backups_for_pruning(
        files, timezone.now().replace(tzinfo=None)
    )

    for path in delete:
        try:
            path.unlink()
            log.info("backup.prune.deleted file=%s", path.name)
        except Exception:
            log.exception("backup.prune.delete_failed file=%s", path.name)

    log.info(
        "backup.prune.done kept=%s deleted=%s unrecognised=%s dir=%s",
        len(keep),
        len(delete),
        unrecognised,
        backup_dir,
    )
    return {
        "kept": len(keep),
        "deleted": len(delete),
        "unrecognised": unrecognised,
    }


# Keep the rate-limit ledger well beyond the widest guard window (7 days) so a
# little history remains for forensic review, but bounded so the table can't
# grow without limit.
_ACTION_RATE_LOG_RETENTION = datetime.timedelta(days=30)


@db_periodic_task(crontab(hour="4", minute="30"), retries=2, retry_delay=600)
def prune_old_action_rate_log() -> int:
    """Delete ``ActionRateLog`` rows older than the retention window.

    ``ActionRateLog`` is a public-schema (SHARED_APPS) table holding every
    tenant's rate-limited-action events, so a single delete prunes all tenants
    at once. Returns the number of rows removed (for the dev/QA runner).
    """
    from apps.shared.tenants.models import ActionRateLog

    cutoff = timezone.now() - _ACTION_RATE_LOG_RETENTION
    deleted, _ = ActionRateLog.objects.filter(created_at__lt=cutoff).delete()
    log.info("action_rate_log.prune.done deleted=%s cutoff=%s", deleted, cutoff)
    return deleted
