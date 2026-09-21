"""Huey periodic tasks for the tenants app.

Currently a single task: ``weekly_tenant_health_report``.

Bootstrap reminder: nothing in this file runs until a Huey worker process
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
    r"^.+?_(?P<timestamp>\d{8}_\d{6})\.(?P<kind>sql|tar)\.gz\.gpg$"
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
        timestamp = datetime.datetime.strptime(
            match.group("timestamp"), "%Y%m%d_%H%M%S"
        )
    except ValueError:
        return None
    return timestamp, match.group("kind")


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

    Retention rule (mirrors the published GDPR retention policy):

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
        parsed_backup = _parse_backup(path.name)
        if parsed_backup is None:
            keep.append(path)
            continue
        timestamp, kind = parsed_backup
        parsed.append((path, timestamp, kind))

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

    for path, timestamp, kind in parsed:
        if timestamp >= daily_cutoff:
            # Daily tier — keep every backup.
            keep.append(path)
            continue
        if timestamp >= weekly_cutoff:
            iso_year, iso_week, _ = timestamp.isocalendar()
            key = (kind, iso_year, iso_week)
            if key in seen_week:
                delete.append(path)
            else:
                seen_week.add(key)
                keep.append(path)
            continue
        # Monthly tier — kept forever, one per calendar month.
        key = (kind, timestamp.year, timestamp.month)
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


# ---------------------------------------------------------------
# Backup freshness alerting
# ---------------------------------------------------------------


# The artifact kinds ``backups/backup.sh`` writes every night, mapped to the
# wording the alert email uses. Both are checked INDEPENDENTLY: a DB dump that
# lands on time says nothing about whether the media archive (invoice /
# delivery-note PDFs, e-invoice XML, consent documents, tenant logos) was
# written, and one masking the other is the failure this alert exists for.
# The keys mirror the ``kind`` alternation in ``_BACKUP_FILENAME_RE``.
BACKUP_KINDS: dict[str, str] = {
    "sql": "database dump",
    "tar": "media archive",
}


def _backup_max_age() -> datetime.timedelta:
    """How old the newest artifact of a kind may get before we alert.

    Mirrors ``_backup_dir()``: a setting rather than a literal so ops can widen
    the window from the environment (a less-than-daily backup schedule) without
    a code change. The 36 h default tolerates one missed 02:00 run plus clock
    skew without crying wolf.
    """
    hours = int(getattr(settings, "BACKUP_MAX_AGE_HOURS", 36))
    return datetime.timedelta(hours=hours)


def stale_backup_kinds(
    paths: Iterable[Path],
    now: datetime.datetime,
    max_age: datetime.timedelta,
) -> dict[str, datetime.datetime | None]:
    """Return ``{kind: newest timestamp}`` for each kind that is NOT fresh.

    Pure function — no filesystem, no clock — so the decision logic is
    testable in isolation, like ``classify_backups_for_pruning``.

    A ``None`` value means no artifact of that kind is present at all. That is
    louder than a stale one: a stale artifact proves backups once worked and
    have since stopped, while ``None`` can also mean they never ran here.

    Filenames ``_parse_backup`` doesn't recognise are skipped rather than
    counted — a stray README or a half-written upload must not pass for a
    fresh dump. (The prune keeps such files for the same reason it can't date
    them; neither guesses at a file it cannot identify.)
    """
    newest: dict[str, datetime.datetime] = {}
    for path in paths:
        parsed = _parse_backup(path.name)
        if parsed is None:
            continue
        timestamp, kind = parsed
        if kind not in newest or timestamp > newest[kind]:
            newest[kind] = timestamp

    cutoff = now - max_age
    return {
        kind: newest.get(kind)
        for kind in BACKUP_KINDS
        if kind not in newest or newest[kind] < cutoff
    }


def _describe_backup_kind(
    kind: str, newest: datetime.datetime | None, now: datetime.datetime
) -> str:
    """One line per problem kind for the alert email body."""
    label = BACKUP_KINDS.get(kind, kind)
    if newest is None:
        return f"  {label} ({kind}): NO artifact at all in the backup directory"
    age_hours = (now - newest).total_seconds() / 3600
    return (
        f"  {label} ({kind}): newest is {newest:%Y-%m-%d %H:%M} ({age_hours:.1f} h old)"
    )


def _mail_admins_safely(subject: str, message: str, *, log_key: str) -> bool:
    """Send an admin alert, reporting whether it actually went out.

    A broken mail backend must not fail the sweep — the structured log line is
    written either way — and the boolean keeps an undelivered alert visible in
    the task's summary instead of reading as a clean run.
    """
    try:
        mail_admins(subject=subject, message=message)
    except Exception:
        log.exception(log_key)
        return False
    return True


@db_periodic_task(crontab(hour="6", minute="10"), retries=2, retry_delay=600)
def alert_on_stale_backups() -> dict[str, int]:
    """Alert when a nightly backup artifact has stopped appearing.

    Backup CREATION is ``crond`` inside the dedicated ``backup`` container and
    depends on neither Django nor Huey, so when that container dies or loses
    its cron the nightly dump simply never runs and the newest artifact quietly
    ages — nothing else notices. This checks the newest DB dump and the newest
    media archive INDEPENDENTLY and emails ``settings.ADMINS`` when either is
    older than ``settings.BACKUP_MAX_AGE_HOURS`` or absent entirely.

    Runs at 06:10: clear of the 02:00 backup (a late-starting dump has
    finished) and of the 05:00 prune, and off the ``*/15`` sweep grid.

    Only the LOCAL backup directory is visible from here; the off-host rclone
    copy is not checked.

    Known limitation — this task runs IN Huey, so it cannot detect its own
    container being down: a dead Huey means no check runs and no alert is sent.
    It detects a dead ``backup`` container, which is the likelier failure,
    while the Huey container has its own liveness signal (``huey_heartbeat``
    drives the compose healthcheck). An outside-in check covering both belongs
    in Uptime Kuma (the ``uptime_kuma_data`` volume), not here.

    Returns ``{"kinds_checked": N, "stale": N, "missing": N, "alerts": N}``
    for the dev/QA runner.
    """
    backup_dir = _backup_dir()
    max_age = _backup_max_age()
    # Filename timestamps come from ``date`` inside the backup container, which
    # sets no TZ and so writes UTC; compare against a naive UTC now, exactly as
    # the prune does. Any residual skew is hours, the threshold is a day and a
    # half.
    now = timezone.now().replace(tzinfo=None)

    try:
        files = [p for p in backup_dir.iterdir() if p.is_file()]
    except OSError:
        # Unlike the prune — which no-ops on a missing directory — an unreadable
        # backup directory is alerted on: a lost volume mount would otherwise
        # silently disable the very alert that is supposed to notice silence.
        log.error("backup.freshness.no_dir dir=%s", backup_dir, exc_info=True)
        sent = _mail_admins_safely(
            subject="[Jasmin] backup freshness UNKNOWN — cannot read the backup directory",
            message=(
                f"The backup-freshness check could not read {backup_dir}.\n\n"
                "Backup artifacts cannot be checked at all, so a stopped "
                "backup would go unnoticed. Check the huey container's "
                "./backups volume mount and the directory's permissions."
            ),
            log_key="backup.freshness.alert_failed",
        )
        return {"kinds_checked": 0, "stale": 0, "missing": 0, "alerts": int(sent)}

    problems = stale_backup_kinds(files, now, max_age)
    if not problems:
        log.info(
            "backup.freshness.ok kinds=%s max_age=%s dir=%s",
            len(BACKUP_KINDS),
            max_age,
            backup_dir,
        )
        return {
            "kinds_checked": len(BACKUP_KINDS),
            "stale": 0,
            "missing": 0,
            "alerts": 0,
        }

    missing = sum(1 for newest in problems.values() if newest is None)
    for kind, newest in sorted(problems.items()):
        log.error(
            "backup.freshness.stale kind=%s newest=%s max_age=%s dir=%s",
            kind,
            newest.isoformat() if newest else "none",
            max_age,
            backup_dir,
        )

    detail = "\n".join(
        _describe_backup_kind(kind, newest, now)
        for kind, newest in sorted(problems.items())
    )
    labels = ", ".join(BACKUP_KINDS.get(kind, kind) for kind in sorted(problems))
    sent = _mail_admins_safely(
        subject=f"[Jasmin] backup freshness alert — {labels}",
        message=(
            f"No fresh backup artifact within {max_age} for:\n\n{detail}\n\n"
            f"Directory checked: {backup_dir} (local copy only — the off-host "
            "rclone copy is not visible from here).\n\n"
            "Backups are written at 02:00 by crond in the 'backup' container. "
            "Check that it is up and its cron is installed:\n"
            "  docker compose ps backup\n"
            "  docker compose exec backup crontab -l\n"
            "  docker compose logs backup | tail -50\n"
            "A one-shot run: docker compose exec backup "
            "/usr/local/bin/backup.sh now"
        ),
        log_key="backup.freshness.alert_failed",
    )
    return {
        "kinds_checked": len(BACKUP_KINDS),
        "stale": len(problems) - missing,
        "missing": missing,
        "alerts": int(sent),
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
