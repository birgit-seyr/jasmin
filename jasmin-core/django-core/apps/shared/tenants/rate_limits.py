"""Per-tenant volume caps on consequential, hard-to-reverse actions.

The threat this defends against is NOT anonymous flooding (that is the edge
WAF's / DRF throttle's job, per-IP request rate). It is an *authenticated,
authorised* office account — or a stolen office token — generating a flood of
legally-relevant records (finalized invoices, SEPA charge runs, the member
register). That is an abuse/quota problem, so the control is a durable,
DB-backed count, not a cache-backed rate limiter.

Two properties make it robust:

1. **Durable.** The count comes from the ``ActionRateLog`` ledger (Postgres),
   not a Redis counter — a cache flush must not reset a legal-safety cap.
2. **Owned above the attacker.** The effective cap is the code default here,
   optionally overridden per-tenant on the *public-schema* ``Tenant`` row
   (``action_rate_limit_overrides``), which is editable only via the
   super-admin platform. An office account has no write path to it, so it
   cannot raise its own ceiling.

Call :func:`enforce_action_quota` at the choke point of each guarded verb,
INSIDE the caller's ``@transaction.atomic`` block. The count+insert is NOT
serialized by any lock — finalization's advisory lock (``pg_advisory_xact_lock``
in ``assign_final_number``) is taken AFTER this guard runs, so concurrent
callers can read the same pre-insert count and admit a few extra past the weekly
ceiling. That overshoot is bounded by the per-minute burst cap and is immaterial
for a flood-prevention safety cap (the goal is to stop thousands, not to be
off-by-none at the boundary). For a legitimately bursty bulk path (e.g. a CSV
import) call :func:`enforce_action_quota_batch`, which reserves the whole batch
against the weekly ceiling up front and skips the per-minute cap.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.core.mail import mail_admins
from django.db import connection, transaction
from django.utils import timezone

from apps.shared.tenants.errors import ActionRateLimitExceeded
from apps.shared.tenants.models import ActionRateLog, RateLimitedAction

# The "authz" logger routes to the security log — a refused (blocked) attempt is
# a security-relevant signal (possible compromised office account) that would
# otherwise leave no trace (the block raises before any ActionRateLog row).
_security_log = logging.getLogger("authz")

_WEEKLY = "weekly"
_PER_MINUTE = "per_minute"

# Safe baseline caps every tenant gets with zero configuration. Set with
# generous headroom over normal volume: the cap exists to stop a runaway flood
# (thousands), NOT to police normal week-to-week variance. Tightening or
# loosening for a specific tenant is a PLATFORM concern — super-admin edits
# ``Tenant.action_rate_limit_overrides`` (see the field's docstring for why it
# deliberately does not live in tenant-editable settings).
#
#   weekly     — rolling 7-day ceiling; catches a slow-drip flood.
#   per_minute — rolling 60-second ceiling; catches a scripted burst. A human
#                clicking through the UI never approaches these, so tripping one
#                is a strong automated-abuse signal.
DEFAULT_ACTION_RATE_LIMITS: dict[str, dict[str, int]] = {
    RateLimitedAction.INVOICE_FINALIZATION: {_WEEKLY: 300, _PER_MINUTE: 20},
    RateLimitedAction.DELIVERY_NOTE_FINALIZATION: {_WEEKLY: 500, _PER_MINUTE: 20},
    # A charge "run" is one action that emits many member charges, so runs are
    # infrequent even for weekly billing — a tight cap is safe here.
    RateLimitedAction.SEPA_CHARGE_GENERATION: {_WEEKLY: 50, _PER_MINUTE: 5},
    RateLimitedAction.MEMBER_CREATION: {_WEEKLY: 1000, _PER_MINUTE: 30},
    RateLimitedAction.USER_CREATION: {_WEEKLY: 1000, _PER_MINUTE: 30},
    RateLimitedAction.SUBSCRIPTION_CONFIRMATION: {_WEEKLY: 1000, _PER_MINUTE: 30},
}

# Emit a (non-blocking) ops alert once weekly volume crosses this fraction of
# the cap, so a human is warned BEFORE the wall — and notices if the wall ever
# starts biting legitimate year-end batches.
_ALERT_FRACTION = 0.8

_WEEK = timedelta(days=7)
_MINUTE = timedelta(seconds=60)


def resolve_action_rate_limit(tenant: Any, action: str) -> tuple[int, int]:
    """Return ``(weekly_cap, per_minute_cap)`` for ``action`` on ``tenant``.

    The per-tenant override (super-admin owned) wins per-bound; any missing
    bound falls back to the code default. A malformed override entry (non-dict,
    non-int) is ignored in favour of the default rather than crashing the guard.
    """
    default = DEFAULT_ACTION_RATE_LIMITS[action]
    overrides = getattr(tenant, "action_rate_limit_overrides", None) or {}
    override = overrides.get(action) if isinstance(overrides, dict) else None
    if not isinstance(override, dict):
        override = {}

    def _bound(key: str) -> int:
        raw = override.get(key, default[key])
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return default[key]
        # A non-positive override would disable the cap entirely; treat it as
        # "unset" and fall back to the protective default.
        return value if value > 0 else default[key]

    return _bound(_WEEKLY), _bound(_PER_MINUTE)


def enforce_action_quota(
    action: str,
    *,
    actor: Any = None,
    tenant: Any = None,
) -> None:
    """Refuse ``action`` if the tenant is over its cap; otherwise record it.

    Raises :class:`ActionRateLimitExceeded` (HTTP 429) when either the rolling
    weekly or the rolling per-minute ceiling is already reached. On success it
    appends one ``ActionRateLog`` row and, as weekly volume crosses 80% of the
    cap, fires a one-shot ops alert.

    ``tenant`` defaults to ``connection.tenant``. With no tenant context (public
    schema / super-admin paths) the guard is a no-op — there is nothing to cap.
    ``actor`` may be a user instance or an id; only its pk is stored.
    """
    tenant, schema = _resolve_guarded_tenant(tenant)
    if schema is None:
        return

    weekly_cap, per_minute_cap = resolve_action_rate_limit(tenant, action)
    now = timezone.now()
    recent = ActionRateLog.objects.filter(tenant_schema=schema, action=action)

    actor_pk = getattr(actor, "pk", actor)

    weekly_count = recent.filter(created_at__gte=now - _WEEK).count()
    if weekly_count >= weekly_cap:
        _raise_blocked(schema, action, _WEEKLY, weekly_cap, actor_pk)

    minute_count = recent.filter(created_at__gte=now - _MINUTE).count()
    if minute_count >= per_minute_cap:
        _raise_blocked(schema, action, _PER_MINUTE, per_minute_cap, actor_pk)

    ActionRateLog.objects.create(
        tenant_schema=schema,
        action=action,
        actor_id=str(actor_pk) if actor_pk else "",
    )
    _maybe_alert(tenant, action, weekly_count, weekly_count + 1, weekly_cap)


def enforce_action_quota_batch(
    action: str,
    *,
    count: int,
    actor: Any = None,
    tenant: Any = None,
) -> list[str]:
    """Reserve WEEKLY quota for a bulk operation creating ``count`` records.

    For a legitimately bursty path (e.g. a CSV member import) the per-minute
    burst cap does not apply — but the weekly ceiling still must, so interactive
    and bulk creation share one budget. Refuses the WHOLE batch up front if it
    would exceed the weekly cap (an import never partially applies), otherwise
    records ``count`` ledger rows. No-op for ``count <= 0`` or no tenant context.

    Returns the pks of the reserved ledger rows. A caller that ends up creating
    FEWER than ``count`` records (an import with failed/blank rows) should refund
    the difference with :func:`release_action_quota` so unfulfilled reservations
    don't permanently consume the weekly budget.
    """
    if count <= 0:
        return []
    tenant, schema = _resolve_guarded_tenant(tenant)
    if schema is None:
        return []

    weekly_cap, _ = resolve_action_rate_limit(tenant, action)
    now = timezone.now()
    weekly_count = ActionRateLog.objects.filter(
        tenant_schema=schema, action=action, created_at__gte=now - _WEEK
    ).count()
    actor_pk = getattr(actor, "pk", actor)
    if weekly_count + count > weekly_cap:
        _raise_blocked(schema, action, _WEEKLY, weekly_cap, actor_pk, batch=count)

    actor_id = str(actor_pk) if actor_pk else ""
    created = ActionRateLog.objects.bulk_create(
        [
            ActionRateLog(tenant_schema=schema, action=action, actor_id=actor_id)
            for _ in range(count)
        ]
    )
    _maybe_alert(tenant, action, weekly_count, weekly_count + count, weekly_cap)
    return [row.pk for row in created]


def release_action_quota(row_ids: list[str]) -> None:
    """Refund reserved batch quota by deleting the given ledger rows.

    A bulk path reserves an upper bound up front (to refuse an over-cap batch
    before doing any work) and calls this afterwards with the pks of the reserved
    rows that did NOT result in a created record. Safe to call with an empty or
    partial list.
    """
    if not row_ids:
        return
    ActionRateLog.objects.filter(pk__in=row_ids).delete()


def _raise_blocked(
    schema: str,
    action: str,
    scope: str,
    limit: int,
    actor_pk: Any,
    *,
    batch: int | None = None,
) -> None:
    """Log the refused attempt to the security log, then raise the 429.

    The block raises before any ``ActionRateLog`` row is written, so without this
    the refusal leaves no trace at all — yet it is exactly the signal of a
    compromised office account flooding a capped verb."""
    _security_log.warning(
        "ratelimit.blocked tenant=%s action=%s scope=%s limit=%s actor=%s%s",
        schema,
        action,
        scope,
        limit,
        actor_pk or "-",
        f" batch={batch}" if batch is not None else "",
    )
    raise ActionRateLimitExceeded(action=action, scope=scope, limit=limit)


def _resolve_guarded_tenant(tenant: Any) -> tuple[Any, str | None]:
    """Return ``(tenant, schema)`` for a guardable request, or ``(tenant, None)``
    to skip.

    Guards only the request path: a fully-loaded ``Tenant`` (has a pk) carries
    the office actor we defend against. A schema-only ``FakeTenant`` (public
    schema, or a background ``schema_context`` task) has no pk — those are
    operator-initiated, not the attack surface — so they pass through uncapped.
    """
    if tenant is None:
        tenant = getattr(connection, "tenant", None)
    if tenant is None or getattr(tenant, "pk", None) is None:
        return tenant, None
    return tenant, (getattr(tenant, "schema_name", None) or None)


def _maybe_alert(
    tenant: Any, action: str, prev_count: int, new_count: int, weekly_cap: int
) -> None:
    """Fire the one-shot ops alert as the weekly total first crosses 80% of the
    cap. ``max(1, ...)`` keeps the warning meaningful for a tiny cap (a cap of 1
    would otherwise floor the threshold to 0 and never alert). Under heavy
    concurrency the lock-free count can step over the exact crossing — acceptable
    for a soft, best-effort heads-up; the hard block is unaffected."""
    alert_threshold = max(1, int(weekly_cap * _ALERT_FRACTION))
    if prev_count < alert_threshold <= new_count:
        _notify_ops_approaching_cap(tenant, action, new_count, weekly_cap)


def _notify_ops_approaching_cap(
    tenant: Any, action: str, current: int, cap: int
) -> None:
    """Best-effort ops heads-up; never let an alert failure break the action.

    Deferred to ``transaction.on_commit`` so the (synchronous SMTP) send happens
    AFTER the caller's transaction commits — it never blocks inside an open
    transaction, and it does NOT fire for an attempt that later rolls back (e.g. a
    finalize that hits a downstream error). Outside a transaction, on_commit runs
    the callback immediately."""
    subject = f"[jasmin] {tenant.name}: '{action}' at {current}/{cap} this week"
    body = (
        f"Tenant '{tenant.name}' (schema {tenant.schema_name}) has reached "
        f"{current} '{action}' actions in the last 7 days, which is 80% of the "
        f"cap of {cap}.\n\n"
        "This is an early warning, not a block. If this is legitimate volume, "
        "a platform administrator can raise the cap via the tenant's "
        "action_rate_limit_overrides. If it is unexpected, the office account "
        "may be compromised — investigate the ActionRateLog for this tenant."
    )
    transaction.on_commit(lambda: mail_admins(subject, body, fail_silently=True))
