"""Tests for the per-tenant action rate-limit guard.

Covers the security-critical core: the durable ledger count, the weekly and
per-minute ceilings, the platform-owned override resolution (including the
malformed / cap-disabling inputs a compromised config must not be able to
exploit), the 7-day window, the 80% ops alert, and the actor trail.

The ``tenant`` fixture calls ``connection.set_tenant(...)`` and yields the
public ``Tenant`` row, so ``connection.tenant`` is live and overrides can be
tuned in memory (no save needed — ``resolve_action_rate_limit`` reads the
attribute).
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import connection
from django.utils import timezone

from apps.shared.tenants.errors import ActionRateLimitExceeded
from apps.shared.tenants.models import ActionRateLog, RateLimitedAction
from apps.shared.tenants.rate_limits import (
    DEFAULT_ACTION_RATE_LIMITS,
    enforce_action_quota,
    enforce_action_quota_batch,
    release_action_quota,
    resolve_action_rate_limit,
)

INV = RateLimitedAction.INVOICE_FINALIZATION
SEPA = RateLimitedAction.SEPA_CHARGE_GENERATION


def _set_override(tenant, *, weekly=None, per_minute=None, action=INV):
    entry = {}
    if weekly is not None:
        entry["weekly"] = weekly
    if per_minute is not None:
        entry["per_minute"] = per_minute
    tenant.action_rate_limit_overrides = {str(action): entry}


def _count(tenant, action=INV):
    return ActionRateLog.objects.filter(
        tenant_schema=tenant.schema_name, action=action
    ).count()


# --------------------------------------------------------------------------- #
# Enforcement                                                                  #
# --------------------------------------------------------------------------- #


def test_records_a_row_and_allows_under_cap(tenant):
    _set_override(tenant, weekly=5, per_minute=5)
    for _ in range(3):
        enforce_action_quota(INV, tenant=tenant)
    assert _count(tenant) == 3


def test_weekly_cap_raises_and_refused_call_records_nothing(tenant):
    _set_override(tenant, weekly=2, per_minute=100)
    enforce_action_quota(INV, tenant=tenant)
    enforce_action_quota(INV, tenant=tenant)

    with pytest.raises(ActionRateLimitExceeded) as exc:
        enforce_action_quota(INV, tenant=tenant)

    assert exc.value.http_status == 429
    assert exc.value.code == "ratelimit.action_exceeded"
    assert exc.value.details == {
        "action": str(INV),
        "scope": "weekly",
        "limit": 2,
    }
    # The refused call must not append a ledger row.
    assert _count(tenant) == 2


def test_per_minute_cap_raises_before_weekly(tenant):
    _set_override(tenant, weekly=1000, per_minute=2)
    enforce_action_quota(INV, tenant=tenant)
    enforce_action_quota(INV, tenant=tenant)

    with pytest.raises(ActionRateLimitExceeded) as exc:
        enforce_action_quota(INV, tenant=tenant)

    assert exc.value.details["scope"] == "per_minute"
    assert exc.value.details["limit"] == 2


def test_rows_outside_the_seven_day_window_do_not_count(tenant):
    _set_override(tenant, weekly=2, per_minute=100)
    enforce_action_quota(INV, tenant=tenant)
    enforce_action_quota(INV, tenant=tenant)
    # Age both rows past the weekly window.
    ActionRateLog.objects.filter(tenant_schema=tenant.schema_name, action=INV).update(
        created_at=timezone.now() - timedelta(days=8)
    )
    # The window is empty again, so a third call is allowed.
    enforce_action_quota(INV, tenant=tenant)
    recent = ActionRateLog.objects.filter(
        tenant_schema=tenant.schema_name,
        action=INV,
        created_at__gte=timezone.now() - timedelta(days=7),
    ).count()
    assert recent == 1


def test_actions_are_capped_independently(tenant):
    tenant.action_rate_limit_overrides = {
        str(INV): {"weekly": 1, "per_minute": 100},
        str(SEPA): {"weekly": 1, "per_minute": 100},
    }
    enforce_action_quota(INV, tenant=tenant)
    # A different action is unaffected by the invoice ledger.
    enforce_action_quota(SEPA, tenant=tenant)
    with pytest.raises(ActionRateLimitExceeded):
        enforce_action_quota(INV, tenant=tenant)


def test_actor_pk_is_recorded(tenant, user):
    enforce_action_quota(INV, tenant=tenant, actor=user)
    row = ActionRateLog.objects.filter(
        tenant_schema=tenant.schema_name, action=INV
    ).latest("created_at")
    assert row.actor_id == str(user.pk)


def test_defaults_to_connection_tenant_when_not_passed(tenant):
    # The ``tenant`` fixture already did connection.set_tenant(tenant).
    enforce_action_quota(INV)
    assert _count(tenant) == 1


def test_noop_without_tenant_context(tenant):
    connection.set_schema_to_public()
    try:
        # No real tenant on the connection → guard is a no-op, never raises.
        enforce_action_quota(INV)
    finally:
        connection.set_tenant(tenant)
    assert _count(tenant) == 0


# --------------------------------------------------------------------------- #
# Override resolution (the platform-owned cap the attacker cannot touch)       #
# --------------------------------------------------------------------------- #


def test_resolve_uses_defaults_with_no_override(tenant):
    tenant.action_rate_limit_overrides = {}
    default = DEFAULT_ACTION_RATE_LIMITS[INV]
    assert resolve_action_rate_limit(tenant, INV) == (
        default["weekly"],
        default["per_minute"],
    )


def test_resolve_partial_override_keeps_default_for_missing_bound(tenant):
    tenant.action_rate_limit_overrides = {str(INV): {"weekly": 7}}
    weekly, per_minute = resolve_action_rate_limit(tenant, INV)
    assert weekly == 7
    assert per_minute == DEFAULT_ACTION_RATE_LIMITS[INV]["per_minute"]


@pytest.mark.parametrize("bad_entry", ["garbage", None, [], 5])
def test_resolve_ignores_malformed_action_entry(tenant, bad_entry):
    tenant.action_rate_limit_overrides = {str(INV): bad_entry}
    default = DEFAULT_ACTION_RATE_LIMITS[INV]
    assert resolve_action_rate_limit(tenant, INV) == (
        default["weekly"],
        default["per_minute"],
    )


@pytest.mark.parametrize("bad_overrides", ["not a dict", None, 42, []])
def test_resolve_ignores_non_dict_overrides(tenant, bad_overrides):
    tenant.action_rate_limit_overrides = bad_overrides
    default = DEFAULT_ACTION_RATE_LIMITS[INV]
    assert resolve_action_rate_limit(tenant, INV) == (
        default["weekly"],
        default["per_minute"],
    )


@pytest.mark.parametrize("bad_bound", [0, -5, "abc", None])
def test_resolve_non_positive_or_unparseable_bound_falls_back(tenant, bad_bound):
    # A 0/negative/garbage override must NOT silently disable the cap.
    tenant.action_rate_limit_overrides = {
        str(INV): {"weekly": bad_bound, "per_minute": bad_bound}
    }
    default = DEFAULT_ACTION_RATE_LIMITS[INV]
    assert resolve_action_rate_limit(tenant, INV) == (
        default["weekly"],
        default["per_minute"],
    )


def test_override_can_tighten_below_default(tenant):
    # SEPA default weekly is well above 1; a super-admin can tighten it.
    tenant.action_rate_limit_overrides = {str(SEPA): {"weekly": 1}}
    enforce_action_quota(SEPA, tenant=tenant)
    with pytest.raises(ActionRateLimitExceeded):
        enforce_action_quota(SEPA, tenant=tenant)


# --------------------------------------------------------------------------- #
# Ops alert                                                                    #
# --------------------------------------------------------------------------- #


# The alert send is deferred via transaction.on_commit, so tests execute the
# captured callbacks (pytest's rolled-back db transaction never commits on its
# own) with the django_capture_on_commit_callbacks fixture.
def test_ops_alert_fires_once_as_weekly_volume_crosses_80_percent(
    tenant, django_capture_on_commit_callbacks
):
    _set_override(tenant, weekly=5, per_minute=100)  # 80% of 5 == 4
    with patch("apps.shared.tenants.rate_limits.mail_admins") as mailer:
        for _ in range(3):  # totals 1,2,3 — below the threshold
            with django_capture_on_commit_callbacks(execute=True):
                enforce_action_quota(INV, tenant=tenant)
        assert mailer.call_count == 0

        with django_capture_on_commit_callbacks(execute=True):
            enforce_action_quota(INV, tenant=tenant)  # total 4 — crosses threshold
        assert mailer.call_count == 1

        with django_capture_on_commit_callbacks(execute=True):
            enforce_action_quota(INV, tenant=tenant)  # total 5 — no repeat alert
        assert mailer.call_count == 1


def test_ops_alert_fires_even_for_a_cap_of_one(
    tenant, django_capture_on_commit_callbacks
):
    # int(1 * 0.8) == 0 used to floor the threshold to 0 and never alert.
    _set_override(tenant, weekly=1, per_minute=100)
    with patch("apps.shared.tenants.rate_limits.mail_admins") as mailer:
        with django_capture_on_commit_callbacks(execute=True):
            enforce_action_quota(INV, tenant=tenant)  # the single allowed action
        assert mailer.call_count == 1


# --------------------------------------------------------------------------- #
# Batch reservation (bulk paths, e.g. CSV import)                              #
# --------------------------------------------------------------------------- #


def test_batch_records_count_rows_under_cap(tenant):
    _set_override(tenant, weekly=100, per_minute=2)
    enforce_action_quota_batch(INV, count=10, tenant=tenant)
    assert _count(tenant) == 10


def test_batch_skips_the_per_minute_burst_cap(tenant):
    # A legitimate bulk import of 10 must pass even though per_minute is 2 —
    # the burst cap does not apply to a batch reservation.
    _set_override(tenant, weekly=100, per_minute=2)
    enforce_action_quota_batch(INV, count=10, tenant=tenant)  # no raise
    assert _count(tenant) == 10


def test_batch_refuses_the_whole_batch_when_it_would_exceed_weekly_cap(tenant):
    _set_override(tenant, weekly=5, per_minute=100)
    with pytest.raises(ActionRateLimitExceeded) as exc:
        enforce_action_quota_batch(INV, count=6, tenant=tenant)
    assert exc.value.details["scope"] == "weekly"
    # Refused up front — nothing recorded, so no partial application.
    assert _count(tenant) == 0


def test_batch_and_interactive_share_one_weekly_budget(tenant):
    _set_override(tenant, weekly=5, per_minute=100)
    enforce_action_quota_batch(INV, count=4, tenant=tenant)  # 4/5 used
    enforce_action_quota(INV, tenant=tenant)  # 5/5 used
    with pytest.raises(ActionRateLimitExceeded):
        enforce_action_quota(INV, tenant=tenant)  # over cap


def test_batch_is_a_noop_for_non_positive_count(tenant):
    _set_override(tenant, weekly=5, per_minute=100)
    enforce_action_quota_batch(INV, count=0, tenant=tenant)
    enforce_action_quota_batch(INV, count=-3, tenant=tenant)
    assert _count(tenant) == 0


def test_batch_returns_reserved_ids_and_release_refunds(tenant):
    _set_override(tenant, weekly=10, per_minute=100)
    ids = enforce_action_quota_batch(INV, count=5, tenant=tenant)
    assert len(ids) == 5
    assert _count(tenant) == 5
    # Refund 2 unfulfilled reservations (e.g. an import where 2 rows failed).
    release_action_quota(ids[3:])
    assert _count(tenant) == 3
    # A later interactive create then still fits under the weekly cap.
    for _ in range(7):
        enforce_action_quota(INV, tenant=tenant)  # 3 + 7 = 10, exactly the cap
    with pytest.raises(ActionRateLimitExceeded):
        enforce_action_quota(INV, tenant=tenant)


def test_release_action_quota_is_safe_on_empty(tenant):
    release_action_quota([])  # no rows, no error


# --------------------------------------------------------------------------- #
# The override is platform-owned — a tenant admin must NOT be able to raise it  #
# --------------------------------------------------------------------------- #


def test_override_is_read_only_on_the_tenant_facing_serializer(tenant):
    # CRITICAL regression: TenantSerializer(fields="__all__") is served for
    # PATCH /api/tenants/tenants/<own_pk>/ to tenant admins. If the override
    # were writable there, a compromised office/admin account could raise its
    # own caps to infinity, defeating the whole feature.
    from apps.shared.tenants.serializers import TenantSerializer

    field = TenantSerializer().fields["action_rate_limit_overrides"]
    assert field.read_only is True


# --------------------------------------------------------------------------- #
# Retention prune                                                              #
# --------------------------------------------------------------------------- #


def test_prune_deletes_rows_past_the_retention_window(tenant):
    from apps.shared.tenants.tasks import prune_old_action_rate_log

    _set_override(tenant, weekly=100, per_minute=100)
    enforce_action_quota(INV, tenant=tenant)
    enforce_action_quota(INV, tenant=tenant)
    # Age one row past the 30-day retention (well beyond the 7-day guard window).
    old = ActionRateLog.objects.filter(tenant_schema=tenant.schema_name).first()
    ActionRateLog.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=31)
    )
    deleted = prune_old_action_rate_log.call_local()
    assert deleted == 1
    assert _count(tenant) == 1
