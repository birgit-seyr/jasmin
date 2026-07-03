"""Tests for ``apps.gdpr.tasks.alert_on_mass_deletes``.

The task watches ``auditlog.LogEntry`` for DELETE actions on
``SENSITIVE_DELETION_MODELS`` (PII / legally-relevant tables) and
alerts when one actor exceeds the threshold within the rolling
window.

We mutate the module-level ``_last_mass_delete_alerted`` dedup state
in some cases, so an autouse fixture clears it between tests.

Tests insert ``LogEntry`` rows directly rather than driving real
deletes through the ORM. django-auditlog needs middleware to set
``actor`` from a request, which doesn't exist in a Huey-task unit
test context. Going through the model layer is the right shape for
end-to-end tests of the audit pipeline (covered in
``apps/payments/tests/test_auditlog.py``); here we just need rows
in the shape the alert will read.
"""

from __future__ import annotations

import datetime
import json
from unittest.mock import patch

import pytest
from auditlog.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from apps.commissioning.models import Member
from apps.commissioning.tests.factories import (
    JasminUserFactory,
)
from apps.gdpr import tasks as gdpr_tasks
from apps.payments.models import BillingProfile


@pytest.fixture(autouse=True)
def _reset_mass_delete_dedup_state():
    gdpr_tasks._last_mass_delete_alerted.clear()
    yield
    gdpr_tasks._last_mass_delete_alerted.clear()


def _log_delete(
    *,
    actor,
    model,
    object_pk: str = "abc123",
    age: datetime.timedelta = datetime.timedelta(minutes=10),
) -> LogEntry:
    """Insert a LogEntry row that looks like a DELETE on ``model``.

    ``timestamp`` is ``auto_now_add``-ish in django-auditlog, so we
    set it via .update() after the insert to get a deterministic
    time inside the test's MASS_DELETE_WINDOW.
    """
    entry = LogEntry.objects.create(
        content_type=ContentType.objects.get_for_model(model),
        object_pk=object_pk,
        object_id=None,
        object_repr=f"{model.__name__}#{object_pk}",
        action=LogEntry.Action.DELETE,
        changes=json.dumps({}),
        actor=actor,
    )
    LogEntry.objects.filter(pk=entry.pk).update(timestamp=timezone.now() - age)
    return entry


@pytest.mark.django_db
class TestMassDeleteAlerts:
    def test_no_alert_below_threshold(self, tenant):
        actor = JasminUserFactory()
        # One fewer than threshold — no burst.
        for i in range(gdpr_tasks.MASS_DELETE_THRESHOLD - 1):
            _log_delete(actor=actor, model=Member, object_pk=f"m{i}")

        with patch.object(gdpr_tasks, "mail_admins") as mock_mail:
            gdpr_tasks.alert_on_mass_deletes.call_local()

        mock_mail.assert_not_called()
        assert not gdpr_tasks._last_mass_delete_alerted

    def test_alerts_at_threshold(self, tenant):
        actor = JasminUserFactory()
        for i in range(gdpr_tasks.MASS_DELETE_THRESHOLD):
            _log_delete(actor=actor, model=Member, object_pk=f"m{i}")

        with patch.object(gdpr_tasks, "mail_admins") as mock_mail:
            gdpr_tasks.alert_on_mass_deletes.call_local()

        mock_mail.assert_called_once()
        kwargs = mock_mail.call_args.kwargs
        assert "mass-delete burst" in kwargs["subject"]
        assert str(actor.pk) in kwargs["message"]
        assert "commissioning.Member" in kwargs["message"]
        assert str(gdpr_tasks.MASS_DELETE_THRESHOLD) in kwargs["message"]
        # Dedup state recorded so the next run inside the cooldown
        # window is suppressed.
        assert (tenant.schema_name, str(actor.pk)) in (
            gdpr_tasks._last_mass_delete_alerted
        )

    def test_alerts_aggregate_across_sensitive_models(self, tenant):
        """Two sensitive models, neither alone over threshold, but the
        SUM by the same actor crosses it."""
        actor = JasminUserFactory()
        half = gdpr_tasks.MASS_DELETE_THRESHOLD // 2 + 1
        for i in range(half):
            _log_delete(actor=actor, model=Member, object_pk=f"m{i}")
            _log_delete(actor=actor, model=BillingProfile, object_pk=f"b{i}")

        with patch.object(gdpr_tasks, "mail_admins") as mock_mail:
            gdpr_tasks.alert_on_mass_deletes.call_local()

        mock_mail.assert_called_once()
        body = mock_mail.call_args.kwargs["message"]
        assert "commissioning.Member" in body
        assert "payments.BillingProfile" in body


@pytest.mark.django_db
class TestNonSensitiveIgnored:
    def test_non_sensitive_model_deletes_dont_trigger(self, tenant):
        """``LogEntry`` for a model NOT in ``SENSITIVE_DELETION_MODELS``
        must not contribute to any actor's burst count."""
        actor = JasminUserFactory()
        # ContentType is itself a non-sensitive table — use it as the
        # stand-in for "some operational model we don't care about".
        ct = ContentType.objects.get_for_model(ContentType)
        # Confirm precondition: this label is genuinely outside the set.
        assert f"{ct.app_label}.{ct.model}" not in {
            m.lower() for m in gdpr_tasks.SENSITIVE_DELETION_MODELS
        }
        for i in range(gdpr_tasks.MASS_DELETE_THRESHOLD * 3):
            LogEntry.objects.create(
                content_type=ct,
                object_pk=f"ct{i}",
                object_repr=f"ContentType#{i}",
                action=LogEntry.Action.DELETE,
                changes=json.dumps({}),
                actor=actor,
            )

        with patch.object(gdpr_tasks, "mail_admins") as mock_mail:
            gdpr_tasks.alert_on_mass_deletes.call_local()

        mock_mail.assert_not_called()


@pytest.mark.django_db
class TestAnonymousActor:
    def test_actor_null_rows_are_ignored(self, tenant):
        """System / migration deletes (``actor_id IS NULL``) must not
        trigger alerts — the retention sweep alone would produce
        constant false positives if they did."""
        for i in range(gdpr_tasks.MASS_DELETE_THRESHOLD * 2):
            _log_delete(actor=None, model=Member, object_pk=f"m{i}")

        with patch.object(gdpr_tasks, "mail_admins") as mock_mail:
            gdpr_tasks.alert_on_mass_deletes.call_local()

        mock_mail.assert_not_called()


@pytest.mark.django_db
class TestWindowAndCooldown:
    def test_deletes_outside_window_are_ignored(self, tenant):
        actor = JasminUserFactory()
        for i in range(gdpr_tasks.MASS_DELETE_THRESHOLD):
            _log_delete(
                actor=actor,
                model=Member,
                object_pk=f"old{i}",
                age=gdpr_tasks.MASS_DELETE_WINDOW + datetime.timedelta(minutes=10),
            )

        with patch.object(gdpr_tasks, "mail_admins") as mock_mail:
            gdpr_tasks.alert_on_mass_deletes.call_local()

        mock_mail.assert_not_called()

    def test_cooldown_suppresses_second_alert(self, tenant):
        actor = JasminUserFactory()
        for i in range(gdpr_tasks.MASS_DELETE_THRESHOLD):
            _log_delete(actor=actor, model=Member, object_pk=f"m{i}")

        with patch.object(gdpr_tasks, "mail_admins") as mock_mail:
            gdpr_tasks.alert_on_mass_deletes.call_local()
        mock_mail.assert_called_once()

        # Second run within cooldown — same burst, no fresh alert.
        with patch.object(gdpr_tasks, "mail_admins") as mock_mail:
            gdpr_tasks.alert_on_mass_deletes.call_local()
        mock_mail.assert_not_called()
