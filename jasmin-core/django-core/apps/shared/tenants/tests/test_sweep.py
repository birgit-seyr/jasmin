"""Tests for the per-tenant sweep helper.

A deactivated tenant is a frozen tenant — server-initiated housekeeping sweeps
must skip it by default (offboarding / non-payment / breach), while an explicit
``include_inactive=True`` opt-in still reaches it (e.g. forensic checks). A
tenant whose work raises is skipped, and the operator gets one email naming it.
"""

from __future__ import annotations

import hashlib
import logging
from unittest import mock

import pytest

from apps.shared.tenants.models import Tenant
from apps.shared.tenants.sweep import SWEEP_FAILURE_ALERT_SECONDS, for_each_tenant


@pytest.mark.django_db
def test_for_each_tenant_skips_inactive_by_default(tenant):
    # Deactivate the (session) tenant for the duration of this test.
    Tenant.objects.filter(pk=tenant.pk).update(is_active=False)

    visited: list[str] = []
    for_each_tenant(lambda t: visited.append(t.schema_name))
    assert tenant.schema_name not in visited

    # …but an explicit opt-in still reaches it.
    visited.clear()
    for_each_tenant(lambda t: visited.append(t.schema_name), include_inactive=True)
    assert tenant.schema_name in visited


@pytest.mark.django_db
def test_for_each_tenant_visits_active(tenant):
    visited: list[str] = []
    for_each_tenant(lambda t: visited.append(t.schema_name))
    assert tenant.schema_name in visited


@pytest.mark.django_db
def test_for_each_tenant_isolates_failures_to_the_caller_logger(tenant):
    """A raising ``work`` is counted and logged to ``logger``, never re-raised."""
    caller_log = logging.getLogger("apps.shared.tenants.tests.sweep")

    def boom(_tenant):
        raise RuntimeError("tenant work failed")

    with mock.patch.object(caller_log, "exception") as logged:
        failures = for_each_tenant(boom, label="test.sweep", logger=caller_log)

    assert failures >= 1
    assert logged.call_count == failures
    assert logged.call_args.args[0] == "%s.tenant_failed tenant=%s"
    assert logged.call_args.args[1] == "test.sweep"


@pytest.mark.django_db
def test_failed_tenants_alert_the_operator_once_with_names_but_no_messages(tenant):
    """The operator hears about failed tenants: their schemas and the exception
    class, never the exception's message, which can carry row values."""

    def boom(_tenant):
        raise RuntimeError("secret row value")

    with mock.patch("apps.shared.tenants.sweep.alert_operator") as alert:
        failures = for_each_tenant(boom, label="test.sweep")

    alert.assert_called_once()
    subject, message = alert.call_args.args
    assert subject == f"test.sweep: {failures} tenant(s) failed"
    assert f"{tenant.schema_name} (RuntimeError)" in message
    assert "secret row value" not in message
    assert "test.sweep.tenant_failed" in message
    assert "docker compose logs huey" in message
    assert alert.call_args.kwargs["throttle_key"].startswith(
        "sweep.tenant_failed:test.sweep:"
    )
    assert alert.call_args.kwargs["throttle_seconds"] == SWEEP_FAILURE_ALERT_SECONDS


@pytest.mark.django_db
def test_the_alert_throttle_is_keyed_on_the_failed_tenants(tenant):
    """The throttle covers the sweep and the set of failed tenants, so a tenant
    that starts failing isn't held back by an earlier alert about another."""

    def boom(_tenant):
        raise RuntimeError("tenant work failed")

    with mock.patch("apps.shared.tenants.sweep.alert_operator") as alert:
        for_each_tenant(boom, label="test.sweep")

    failed = sorted(
        Tenant.objects.exclude(schema_name="public")
        .filter(is_active=True)
        .values_list("schema_name", flat=True)
    )
    expected = hashlib.sha256(",".join(failed).encode()).hexdigest()[:16]
    assert (
        alert.call_args.kwargs["throttle_key"]
        == f"sweep.tenant_failed:test.sweep:{expected}"
    )


@pytest.mark.django_db
def test_a_clean_sweep_alerts_nobody(tenant):
    with mock.patch("apps.shared.tenants.sweep.alert_operator") as alert:
        assert for_each_tenant(lambda _tenant: None, label="test.sweep") == 0

    alert.assert_not_called()
