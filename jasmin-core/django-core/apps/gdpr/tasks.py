"""Huey periodic tasks for the GDPR app.

Three tasks live here:

  * ``anonymise_long_cancelled_members`` — closes the 10-year retention
    clock that ``docs/retention-policy.md`` and the audit checklist
    have been advertising. Without this task, the policy was
    theoretical: an auditor running
    ``Member.objects.filter(cancelled_effective_at__lt=ten_years_ago)``
    would have found PII the policy claimed was erased.

  * ``alert_on_mass_deletes`` — detects mass-deletion bursts on
    PII / legally-relevant tables. The brute-force alert in
    ``apps/accounts/tasks.py`` covers external attacker; this one
    covers internal attacker (compromised office account, rogue
    employee, misconfigured automation).

  * ``alert_on_deletion_endpoint_bursts`` — detects abuse of the
    public-facing GDPR deletion endpoints (lodge + confirm). Per-user
    throttles (5/h on lodge, 10/min on confirm) catch single-account
    abuse. This task catches the cross-account pattern: one IP
    spreading deletion requests across many compromised accounts, OR
    one IP confirming many phished/intercepted tokens. SAR-export
    burst alerting is intentionally NOT included — see the docstring
    on that task for the rationale.

Together with ``alert_on_axes_bursts`` in apps/accounts/tasks.py,
the three "alert_on_*" tasks answer the canonical anomaly classes
an auditor checks under Art. 5(2) accountability + Art. 32 security
of processing: credential stuffing, insider data destruction, and
abuse of public-facing data-subject endpoints.

Bootstrap reminder: nothing in this file runs until the ``HUEY``
config block in ``config/settings.py`` is uncommented and a worker
process starts. Decorators register tasks at import time but the
scheduler needs to be alive to fire them.
"""

from __future__ import annotations

import datetime
import logging
from collections import Counter

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.mail import mail_admins
from django.utils import timezone
from huey import crontab
from huey.contrib.djhuey import db_periodic_task

from apps.commissioning.models import Member
from apps.gdpr.errors import RetentionPeriodActive
from apps.gdpr.services import GDPRService
from apps.shared.tenants.sweep import for_each_tenant

log = logging.getLogger("gdpr")
ops_log = logging.getLogger("tasks")

# GenG §31 / HGB §257 / AO §147 — ten years from the legal exit date is
# the statutory floor. We treat that floor as both the soonest a member
# CAN be anonymised and the SLA: once 10 years elapse, the platform
# erases unless an explicit retention block still applies (open
# CoopShare, open invoice, etc. — those are picked up by
# ``GDPRService.check_retention_blocks``).
EX_MEMBER_RETENTION_YEARS = 10


def _retention_cutoff(today: datetime.date | None = None) -> datetime.date:
    """The latest ``cancelled_effective_at`` value that's STILL within
    the retention window. Members whose date is ``<=`` this are
    candidates for anonymisation."""
    return (today or timezone.localdate()) - relativedelta(
        years=EX_MEMBER_RETENTION_YEARS
    )


def _candidates_for_anonymisation(cutoff: datetime.date):
    """Members past the retention window who haven't been anonymised yet.

    Idempotency key: the anonymisation tombstone on the email column.
    ``GDPRService.anonymize_user`` scrubs the live email to
    ``deleted_<pk>@deleted.invalid``, so an already-anonymised member is
    excluded by that suffix. We must NOT key on ``user.is_active`` — ordinary
    office deactivation (``account_status="inactive"``) also clears it, so a
    cancelled-then-deactivated ex-member would be skipped FOREVER and their PII
    retained past the statutory window. Re-running anonymize_user on a stale row
    is safe (it re-checks retention blocks + scrubs in place), so erring toward
    inclusion is correct.
    """
    return (
        Member.objects.filter(
            cancelled_effective_at__lte=cutoff,
            cancelled_effective_at__isnull=False,
            user__isnull=False,
        )
        .exclude(user__email__endswith="@deleted.invalid")
        .select_related("user")
        .order_by("cancelled_effective_at")
    )


@db_periodic_task(crontab(hour="3", minute="0"), retries=2, retry_delay=600)
def anonymise_long_cancelled_members() -> dict[str, int]:
    """Anonymise ex-members past the 10-year retention window.

    Runs daily at 03:00 (after the prod backup window, before business
    hours so the WARNING/INFO log noise doesn't get lost in the day's
    traffic).

    Per-tenant try/except: a single tenant's failure must not stop the
    rest. Within a tenant, each member's anonymisation runs in its own
    ``@transaction.atomic`` block via
    ``GDPRService.anonymize_user`` — one failed member doesn't roll
    back the others.

    Two log channels per anonymisation:

      * ``gdpr.ex_member_anonymised`` (INFO) — happy path; goes into
        the GDPR audit log for regulator-facing accountability.
      * ``gdpr.ex_member_blocked`` (WARNING) — retention block fired
        despite 10y+ elapsed. Usually means open CoopShares, open
        invoices, or active subscriptions that should have been
        closed at member exit. Office needs to clean those up; the
        member will keep showing up here until they do.
    """
    cutoff = _retention_cutoff()
    log.info(
        "gdpr.retention_sweep_start cutoff=%s retention_years=%s",
        cutoff.isoformat(),
        EX_MEMBER_RETENTION_YEARS,
    )

    counters = {"anonymised": 0, "blocked": 0, "tenants_scanned": 0}

    def sweep(tenant) -> None:
        counters["tenants_scanned"] += 1
        anonymised, blocked = _run_for_current_schema(cutoff)
        counters["anonymised"] += anonymised
        counters["blocked"] += blocked

    # ``include_inactive=True``: a legal retention obligation persists on a
    # frozen (is_active=False) tenant, so the erasure SLA must keep running
    # there — matching the pre-adoption loop, which scanned every non-public
    # tenant regardless of active status. Per-tenant failures are isolated
    # and logged (to the gdpr log) so one bad schema never aborts the sweep.
    for_each_tenant(
        sweep, label="gdpr.retention_sweep", logger=log, include_inactive=True
    )

    log.info(
        "gdpr.retention_sweep_done anonymised=%s blocked=%s tenants_scanned=%s",
        counters["anonymised"],
        counters["blocked"],
        counters["tenants_scanned"],
    )
    return {
        "anonymised": counters["anonymised"],
        "blocked": counters["blocked"],
        "tenants_scanned": counters["tenants_scanned"],
    }


def _run_for_current_schema(cutoff: datetime.date) -> tuple[int, int]:
    """Process candidates under the currently-active tenant schema.

    Split out from ``anonymise_long_cancelled_members`` so tests can
    drive it directly without re-entering ``schema_context``.

    Returns ``(anonymised_count, blocked_count)``.
    """
    anonymised = 0
    blocked = 0

    today = timezone.localdate()

    for member in _candidates_for_anonymisation(cutoff).iterator():
        user = member.user
        if user is None:
            continue
        days_since = (today - member.cancelled_effective_at).days
        # ``GDPRService.anonymize_user`` is already
        # ``@transaction.atomic``; a failure rolls back the per-member
        # scrub. The outer loop is intentionally NOT wrapped, so one
        # failing member doesn't poison the rest of the run.
        try:
            GDPRService.anonymize_user(user)
        except RetentionPeriodActive as exc:
            reasons = exc.details.get("reasons", [])
            log.warning(
                "gdpr.ex_member_blocked member_id=%s days_since_cancellation=%s "
                "reasons=%s",
                member.pk,
                days_since,
                "|".join(reasons) or "unknown",
            )
            blocked += 1
        except Exception:
            log.exception(
                "gdpr.ex_member_anonymisation_failed member_id=%s",
                member.pk,
            )
        else:
            log.info(
                "gdpr.ex_member_anonymised member_id=%s " "days_since_cancellation=%s",
                member.pk,
                days_since,
            )
            anonymised += 1

    return anonymised, blocked


# ---------------------------------------------------------------
# Mass-delete anomaly alerting
# ---------------------------------------------------------------

# PII / legally-relevant tables. A mass-delete on these is a security
# event regardless of who performed it. Operational tables that the
# office routinely bulk-deletes during housekeeping (ShareDelivery,
# PaymentCycle, Order/OrderContent, …) are deliberately NOT in this
# set — counting them would drown the signal in noise. Finalized
# invoices / delivery notes / orders are FinalizedProtectedMixin-
# guarded at the ORM layer so bulk deletion fails before it can show
# up here at all.
# ContentType stores ``model`` as the lowercased class name, so we
# match in lowercase. Display names (human-readable, CamelCase) live
# alongside for the log/email payloads.
_SENSITIVE_MODELS_DISPLAY: dict[str, str] = {
    "commissioning.member": "commissioning.Member",
    "commissioning.coopshare": "commissioning.CoopShare",
    "commissioning.subscription": "commissioning.Subscription",
    "commissioning.consentdocument": "commissioning.ConsentDocument",
    "commissioning.consentrecord": "commissioning.ConsentRecord",
    # B2B personal data of sole traders — auditlog-registered PII carriers with
    # their own classification + anonymization; a bulk delete of these must trip
    # the same insider-destruction alert as Member.
    "commissioning.reseller": "commissioning.Reseller",
    "commissioning.contactentity": "commissioning.ContactEntity",
    "payments.billingprofile": "payments.BillingProfile",
}
SENSITIVE_DELETION_MODELS = frozenset(_SENSITIVE_MODELS_DISPLAY.values())

# Threshold aligned with ``AXES_FAILURE_LIMIT`` so a single number
# describes "what's a burst" platform-wide. Bumpable via
# ``settings.MASS_DELETE_THRESHOLD`` for tenants that legitimately
# have higher delete volume on the sensitive set (e.g. a yearly
# membership-cleanup batch).
MASS_DELETE_THRESHOLD = getattr(
    settings,
    "MASS_DELETE_THRESHOLD",
    getattr(settings, "AXES_FAILURE_LIMIT", 5),
)
MASS_DELETE_WINDOW = datetime.timedelta(hours=1)

# Cooldown matches the burst alert: avoid re-emailing about the same
# actor while their burst is still inside the rolling window. In-
# process state — worker restarts reset it, which is fine.
_MASS_DELETE_ALERT_COOLDOWN = datetime.timedelta(hours=1)
_last_mass_delete_alerted: dict[tuple[str, str], datetime.datetime] = {}


@db_periodic_task(crontab(minute="*/15"), retries=2, retry_delay=300)
def alert_on_mass_deletes() -> dict[str, int]:
    """Surface mass-deletion bursts on PII / legally-relevant tables.

    Walks each tenant's ``auditlog.LogEntry`` table for DELETE actions
    in the last hour, restricts to ``SENSITIVE_DELETION_MODELS``,
    groups by actor, and alerts on any actor that hits the threshold.
    The signal is a structured ``audit.mass_delete`` line into
    ``security.log`` plus an ops email via ``ADMINS``.

    Per-tenant try/except: one tenant's failure must not block
    cross-tenant aggregation. Missing data is better than no alert
    for any tenant.

    Anonymous deletes (``actor_id IS NULL``) are skipped — the
    retention sweep above and various migration / management
    commands produce them, and counting them would generate
    constant false positives. ``LogEntry`` rows are still written
    so forensic traceability is preserved; only the alerting layer
    skips them.
    """
    # Resolve the auditlog model lazily — keeps the module importable
    # even if auditlog isn't fully initialised at decorator-time.
    from auditlog.models import LogEntry

    cutoff = timezone.now() - MASS_DELETE_WINDOW
    # (tenant_schema, actor_id) → Counter of "app.Model" → count.
    by_actor: dict[tuple[str, str], Counter[str]] = {}
    counters = {"tenants_scanned": 0}

    def collect(tenant) -> None:
        counters["tenants_scanned"] += 1
        rows = (
            LogEntry.objects.filter(
                action=LogEntry.Action.DELETE,
                timestamp__gte=cutoff,
                actor_id__isnull=False,
            )
            .select_related("content_type")
            .values_list(
                "actor_id",
                "content_type__app_label",
                "content_type__model",
            )
            .iterator()
        )
        for actor_id, app_label, model_name in rows:
            lookup_key = f"{app_label}.{model_name}"
            display = _SENSITIVE_MODELS_DISPLAY.get(lookup_key)
            if display is None:
                continue
            key = (tenant.schema_name, str(actor_id))
            by_actor.setdefault(key, Counter())[display] += 1

    # ``include_inactive=True``: insider data destruction is exactly what a
    # frozen (offboarding / disputed / breached) tenant is at risk of, so the
    # forensic scan must keep watching it — matching the pre-adoption loop over
    # every non-public tenant. Per-tenant failures are isolated (missing data
    # for one tenant beats no alert for any) and logged to the gdpr log.
    for_each_tenant(
        collect, label="audit.mass_delete", logger=log, include_inactive=True
    )

    now = timezone.now()
    fresh_bursts: list[tuple[tuple[str, str], Counter[str], int]] = []
    for key, counter in by_actor.items():
        total = sum(counter.values())
        if total < MASS_DELETE_THRESHOLD:
            continue
        last = _last_mass_delete_alerted.get(key)
        if last is not None and now - last < _MASS_DELETE_ALERT_COOLDOWN:
            continue
        fresh_bursts.append((key, counter, total))
        _last_mass_delete_alerted[key] = now

    for (tenant_schema, actor_id), counter, total in fresh_bursts:
        models_breakdown = ",".join(
            f"{label}:{count}" for label, count in counter.most_common()
        )
        log.warning(
            "audit.mass_delete tenant=%s actor=%s count=%s models=%s "
            "window_hours=%s threshold=%s",
            tenant_schema,
            actor_id,
            total,
            models_breakdown,
            int(MASS_DELETE_WINDOW.total_seconds() // 3600),
            MASS_DELETE_THRESHOLD,
        )

    if fresh_bursts:
        _send_mass_delete_ops_alert(fresh_bursts)

    return {
        "tenants_scanned": counters["tenants_scanned"],
        "actors_with_sensitive_deletes": len(by_actor),
        "fresh_alerts": len(fresh_bursts),
    }


def _send_mass_delete_ops_alert(
    bursts: list[tuple[tuple[str, str], Counter[str], int]],
) -> None:
    """Email ``settings.ADMINS`` about the bursts.

    Uses ``mail_admins`` (Django built-in) so the same SMTP path the
    platform's transactional mail uses also carries this — no extra
    config. The email is short on purpose: ops triage starts in
    ``/admin/auditlog/logentry/`` filtered by actor + last hour.
    """
    lines = ["The following mass-delete bursts crossed the threshold:", ""]
    for (tenant_schema, actor_id), counter, total in bursts:
        models_breakdown = ", ".join(
            f"{label} ×{count}" for label, count in counter.most_common()
        )
        lines.append(
            f"  tenant={tenant_schema} actor={actor_id} count={total} "
            f"({models_breakdown})"
        )
    lines.extend(
        [
            "",
            f"Window: last {int(MASS_DELETE_WINDOW.total_seconds() // 3600)}h",
            f"Threshold: {MASS_DELETE_THRESHOLD}",
            "",
            "Triage at /admin/auditlog/logentry/ filtered by actor + timestamp.",
        ]
    )
    mail_admins(
        subject=f"[jasmin] mass-delete burst ({len(bursts)} actor(s))",
        message="\n".join(lines),
        fail_silently=True,
    )


# ---------------------------------------------------------------
# Deletion-endpoint burst alerting (lodge + confirm)
# ---------------------------------------------------------------

# Threshold for "many deletion-request lodges from one IP" — the
# per-user throttle (5/h, ``gdpr_request_deletion``) catches single-
# user abuse; this catches cross-user / cross-tenant patterns from
# one IP. 5 lodges in an hour from one IP across multiple user
# accounts is wildly above legitimate use (a normal user lodges
# zero or one deletion in their entire membership lifetime).
DELETION_LODGE_BURST_THRESHOLD = getattr(
    settings,
    "DELETION_LODGE_BURST_THRESHOLD",
    5,
)

# Threshold for "many email-confirm clicks from one IP" — the per-IP
# rate limit on the confirm endpoint is 10/min (``gdpr_confirm_deletion``).
# A legitimate user clicks the confirm link ONCE per deletion request.
# 3+ confirms from one IP in an hour means the IP is acting on
# multiple unrelated tokens — phishing harvest, intercepted emails,
# or a compromised inbox. Lower threshold than lodge because the
# baseline of legitimate cross-account confirms from one IP is
# essentially zero.
DELETION_CONFIRM_BURST_THRESHOLD = getattr(
    settings,
    "DELETION_CONFIRM_BURST_THRESHOLD",
    3,
)

DELETION_BURST_WINDOW = datetime.timedelta(hours=1)

# Cooldown matches the other burst alerts. Two separate dedup dicts
# so a lodge burst doesn't suppress a confirm burst (or vice versa)
# from the same IP — they're distinct signals.
_DELETION_BURST_COOLDOWN = datetime.timedelta(hours=1)
_last_lodge_burst_alerted: dict[tuple[str, str], datetime.datetime] = {}
_last_confirm_burst_alerted: dict[tuple[str, str], datetime.datetime] = {}


@db_periodic_task(crontab(minute="*/15"), retries=2, retry_delay=300)
def alert_on_deletion_endpoint_bursts() -> dict[str, int]:
    """Surface abuse of the public-facing GDPR deletion endpoints.

    Two signals, both walked per-tenant:

      * **Lodge burst** — ``DeletionRequest`` rows created in the last
        hour, grouped by ``requested_ip``. Alerts when one IP exceeds
        ``DELETION_LODGE_BURST_THRESHOLD`` across users. ``requested_ip``
        was added in migration ``gdpr/0003`` and is captured by the
        view at request time; pre-0003 rows are skipped.
      * **Confirm spray** — same model, grouped by
        ``email_confirmed_ip``. Alerts when one IP exceeds
        ``DELETION_CONFIRM_BURST_THRESHOLD`` confirmations in an hour.
        Each token confirms exactly once and is bound to one user, so
        cross-user confirms from one IP are a token-spray fingerprint.

    Per-tenant try/except: one tenant's failure must not block
    cross-tenant aggregation. Anonymous (NULL) IPs are skipped on
    both sides — they'd false-positive on legacy rows and on requests
    behind a reverse proxy that wasn't trust-forwarded properly.

    **SAR exports are deliberately NOT included.** The SAR view
    (apps/gdpr/views.py, ``gdpr_my_data_view``) is authenticated +
    rate-limited at 2/h per user via the ``gdpr_sar_export`` throttle
    scope. Cross-user abuse from one IP would require multiple
    compromised credentials, which has its own control via
    ``alert_on_axes_bursts``. Adding a SAR-access model + view rewire
    for a marginal threat-coverage improvement isn't deploy-blocking.
    Tracked in the audit checklist if the threat model shifts.
    """
    from apps.gdpr.models import DeletionRequest

    cutoff = timezone.now() - DELETION_BURST_WINDOW
    # (tenant_schema, ip) → count for each signal type.
    lodge_by_ip: dict[tuple[str, str], int] = {}
    confirm_by_ip: dict[tuple[str, str], int] = {}
    counters = {"tenants_scanned": 0}

    def collect(tenant) -> None:
        counters["tenants_scanned"] += 1
        lodge_rows = (
            DeletionRequest.objects.filter(
                requested_at__gte=cutoff,
                requested_ip__isnull=False,
            )
            .values_list("requested_ip", flat=True)
            .iterator()
        )
        for ip in lodge_rows:
            lodge_by_ip.setdefault((tenant.schema_name, str(ip)), 0)
            lodge_by_ip[(tenant.schema_name, str(ip))] += 1

        confirm_rows = (
            DeletionRequest.objects.filter(
                email_confirmed_at__gte=cutoff,
                email_confirmed_ip__isnull=False,
            )
            .values_list("email_confirmed_ip", flat=True)
            .iterator()
        )
        for ip in confirm_rows:
            confirm_by_ip.setdefault((tenant.schema_name, str(ip)), 0)
            confirm_by_ip[(tenant.schema_name, str(ip))] += 1

    # ``include_inactive=True``: abuse of the public deletion endpoints stays a
    # concern on a frozen tenant, so keep scanning every non-public tenant as
    # the pre-adoption loop did. Per-tenant failures are isolated and logged to
    # the gdpr log so one tenant never blocks cross-tenant aggregation.
    for_each_tenant(
        collect, label="gdpr.deletion_burst", logger=log, include_inactive=True
    )

    now = timezone.now()
    lodge_bursts = _filter_fresh(
        lodge_by_ip,
        DELETION_LODGE_BURST_THRESHOLD,
        _last_lodge_burst_alerted,
        now,
    )
    confirm_bursts = _filter_fresh(
        confirm_by_ip,
        DELETION_CONFIRM_BURST_THRESHOLD,
        _last_confirm_burst_alerted,
        now,
    )

    for (tenant_schema, ip), count in lodge_bursts:
        log.warning(
            "gdpr.deletion_lodge_burst tenant=%s ip=%s count=%s "
            "window_hours=%s threshold=%s",
            tenant_schema,
            ip,
            count,
            int(DELETION_BURST_WINDOW.total_seconds() // 3600),
            DELETION_LODGE_BURST_THRESHOLD,
        )
    for (tenant_schema, ip), count in confirm_bursts:
        log.warning(
            "gdpr.deletion_confirm_burst tenant=%s ip=%s count=%s "
            "window_hours=%s threshold=%s",
            tenant_schema,
            ip,
            count,
            int(DELETION_BURST_WINDOW.total_seconds() // 3600),
            DELETION_CONFIRM_BURST_THRESHOLD,
        )

    if lodge_bursts or confirm_bursts:
        _send_deletion_burst_ops_alert(lodge_bursts, confirm_bursts)

    return {
        "tenants_scanned": counters["tenants_scanned"],
        "lodge_ips_seen": len(lodge_by_ip),
        "confirm_ips_seen": len(confirm_by_ip),
        "lodge_bursts": len(lodge_bursts),
        "confirm_bursts": len(confirm_bursts),
    }


def _filter_fresh(
    counter: dict[tuple[str, str], int],
    threshold: int,
    dedup: dict[tuple[str, str], datetime.datetime],
    now: datetime.datetime,
) -> list[tuple[tuple[str, str], int]]:
    """Drop sub-threshold entries and entries still inside the cooldown
    window. Mutates ``dedup`` to record fresh alerts.

    Shared between the lodge + confirm tracks so the dedup discipline
    stays identical across signals.
    """
    fresh: list[tuple[tuple[str, str], int]] = []
    for key, count in counter.items():
        if count < threshold:
            continue
        last = dedup.get(key)
        if last is not None and now - last < _DELETION_BURST_COOLDOWN:
            continue
        fresh.append((key, count))
        dedup[key] = now
    return fresh


def _send_deletion_burst_ops_alert(
    lodge_bursts: list[tuple[tuple[str, str], int]],
    confirm_bursts: list[tuple[tuple[str, str], int]],
) -> None:
    """Email ``settings.ADMINS`` about the bursts.

    Single email per task run that lists both kinds — ops triage
    starts in the structured log lines (``grep "gdpr.deletion_*_burst"``)
    and continues in the DRF admin / DB for the specific
    ``DeletionRequest`` rows.
    """
    lines: list[str] = []
    if lodge_bursts:
        lines.append("Deletion-request LODGE bursts (one IP across users):")
        for (tenant_schema, ip), count in lodge_bursts:
            lines.append(f"  tenant={tenant_schema} ip={ip} lodges={count}")
        lines.append("")
    if confirm_bursts:
        lines.append("Deletion-confirm bursts (one IP, multiple tokens):")
        for (tenant_schema, ip), count in confirm_bursts:
            lines.append(f"  tenant={tenant_schema} ip={ip} confirms={count}")
        lines.append("")
    lines.extend(
        [
            f"Window: last {int(DELETION_BURST_WINDOW.total_seconds() // 3600)}h",
            f"Lodge threshold: {DELETION_LODGE_BURST_THRESHOLD}",
            f"Confirm threshold: {DELETION_CONFIRM_BURST_THRESHOLD}",
            "",
            "Triage: DeletionRequest filtered by ``requested_ip`` /",
            "``email_confirmed_ip`` + the burst window.",
        ]
    )

    total_bursts = len(lodge_bursts) + len(confirm_bursts)
    mail_admins(
        subject=f"[jasmin] deletion-endpoint burst ({total_bursts} signal(s))",
        message="\n".join(lines),
        fail_silently=True,
    )
