"""Tests for ``apps.gdpr.tasks.alert_on_deletion_endpoint_bursts``.

Two signals: lodge bursts (one IP across users) and confirm sprays
(one IP confirming multiple unrelated tokens). The shape mirrors the
``alert_on_mass_deletes`` tests — module-level dedup state, autouse
clear fixture, ``call_local()`` driver, ``mail_admins`` patched.
"""

from __future__ import annotations

import datetime
import uuid
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.commissioning.tests.factories import JasminUserFactory
from apps.gdpr import tasks as gdpr_tasks
from apps.gdpr.models import DeletionRequest, DeletionRequestState


@pytest.fixture(autouse=True)
def _reset_deletion_burst_dedup_state():
    gdpr_tasks._last_lodge_burst_alerted.clear()
    gdpr_tasks._last_confirm_burst_alerted.clear()
    yield
    gdpr_tasks._last_lodge_burst_alerted.clear()
    gdpr_tasks._last_confirm_burst_alerted.clear()


def _make_lodge(
    *,
    user,
    ip: str | None = "1.2.3.4",
    age: datetime.timedelta = datetime.timedelta(minutes=10),
) -> DeletionRequest:
    """Insert a ``DeletionRequest`` whose ``requested_at`` sits
    ``age`` ago. We bypass ``GDPRService.request_deletion`` so each
    row stays independent (the service supersedes prior open rows
    for the same user)."""
    dr = DeletionRequest.objects.create(
        user=user,
        requested_email=user.email,
        token=uuid.uuid4(),
        token_expires_at=timezone.now() + datetime.timedelta(hours=24),
        requested_ip=ip,
    )
    DeletionRequest.objects.filter(pk=dr.pk).update(requested_at=timezone.now() - age)
    return dr


def _make_confirm(
    *,
    user,
    confirm_ip: str | None = "5.6.7.8",
    age: datetime.timedelta = datetime.timedelta(minutes=10),
) -> DeletionRequest:
    """Insert a ``DeletionRequest`` already confirmed by an IP within
    the burst window."""
    confirmed_at = timezone.now() - age
    # ``requested_at`` is auto_now_add (stamped to now on INSERT), so the row
    # can't be born already-confirmed-in-the-past without violating the
    # request-before-confirm ordering. Create it plain, then backdate both
    # ``requested_at`` (just ahead of the confirmation) and the confirmation
    # fields via .update() so the chronology holds.
    requested_at = confirmed_at - datetime.timedelta(minutes=1)
    dr = DeletionRequest.objects.create(
        user=user,
        requested_email=user.email,
        token=uuid.uuid4(),
        token_expires_at=timezone.now() + datetime.timedelta(hours=24),
        email_confirmed_ip=confirm_ip,
    )
    DeletionRequest.objects.filter(pk=dr.pk).update(
        requested_at=requested_at,
        state=DeletionRequestState.PENDING_ADMIN,
        email_confirmed_at=confirmed_at,
    )
    return dr


@pytest.mark.django_db
class TestLodgeBurst:
    def test_no_alert_below_threshold(self, tenant):
        for _ in range(gdpr_tasks.DELETION_LODGE_BURST_THRESHOLD - 1):
            _make_lodge(user=JasminUserFactory(), ip="9.9.9.9")

        with patch.object(gdpr_tasks, "mail_admins") as mock_mail:
            gdpr_tasks.alert_on_deletion_endpoint_bursts.call_local()
        mock_mail.assert_not_called()

    def test_alerts_at_threshold_for_one_ip_many_users(self, tenant):
        """The interesting case: ONE IP, MANY users — what the per-user
        throttle can't catch."""
        for _ in range(gdpr_tasks.DELETION_LODGE_BURST_THRESHOLD):
            _make_lodge(user=JasminUserFactory(), ip="9.9.9.9")

        with patch.object(gdpr_tasks, "mail_admins") as mock_mail:
            gdpr_tasks.alert_on_deletion_endpoint_bursts.call_local()

        mock_mail.assert_called_once()
        body = mock_mail.call_args.kwargs["message"]
        assert "9.9.9.9" in body
        assert "LODGE" in body
        # Dedup state recorded so a re-run inside the cooldown is
        # suppressed.
        assert (
            tenant.schema_name,
            "9.9.9.9",
        ) in gdpr_tasks._last_lodge_burst_alerted

    def test_null_ip_rows_are_ignored(self, tenant):
        """Legacy rows pre-0003 have ``requested_ip IS NULL``. They
        must not aggregate (would false-positive on a fleet of legacy
        rows that share NULL as a synthetic key)."""
        for _ in range(gdpr_tasks.DELETION_LODGE_BURST_THRESHOLD * 2):
            _make_lodge(user=JasminUserFactory(), ip=None)

        with patch.object(gdpr_tasks, "mail_admins") as mock_mail:
            gdpr_tasks.alert_on_deletion_endpoint_bursts.call_local()
        mock_mail.assert_not_called()


@pytest.mark.django_db
class TestConfirmBurst:
    def test_alerts_at_threshold(self, tenant):
        for _ in range(gdpr_tasks.DELETION_CONFIRM_BURST_THRESHOLD):
            _make_confirm(user=JasminUserFactory(), confirm_ip="42.42.42.42")

        with patch.object(gdpr_tasks, "mail_admins") as mock_mail:
            gdpr_tasks.alert_on_deletion_endpoint_bursts.call_local()

        mock_mail.assert_called_once()
        body = mock_mail.call_args.kwargs["message"]
        assert "42.42.42.42" in body
        assert "confirm" in body.lower()
        assert (
            tenant.schema_name,
            "42.42.42.42",
        ) in gdpr_tasks._last_confirm_burst_alerted

    def test_no_alert_below_threshold(self, tenant):
        for _ in range(gdpr_tasks.DELETION_CONFIRM_BURST_THRESHOLD - 1):
            _make_confirm(user=JasminUserFactory(), confirm_ip="42.42.42.42")

        with patch.object(gdpr_tasks, "mail_admins") as mock_mail:
            gdpr_tasks.alert_on_deletion_endpoint_bursts.call_local()
        mock_mail.assert_not_called()

    def test_lodge_and_confirm_dedup_independent(self, tenant):
        """A lodge burst from IP X must not suppress a separate confirm
        burst from the same IP X — they're distinct signals with
        distinct cooldowns."""
        ip = "7.7.7.7"
        for _ in range(gdpr_tasks.DELETION_LODGE_BURST_THRESHOLD):
            _make_lodge(user=JasminUserFactory(), ip=ip)
        for _ in range(gdpr_tasks.DELETION_CONFIRM_BURST_THRESHOLD):
            _make_confirm(user=JasminUserFactory(), confirm_ip=ip)

        with patch.object(gdpr_tasks, "mail_admins") as mock_mail:
            gdpr_tasks.alert_on_deletion_endpoint_bursts.call_local()

        # Single email summarising both bursts.
        mock_mail.assert_called_once()
        body = mock_mail.call_args.kwargs["message"]
        assert "LODGE" in body
        assert "confirm" in body.lower()
        # Both dedup dicts now hold the IP under separate keys.
        assert (tenant.schema_name, ip) in gdpr_tasks._last_lodge_burst_alerted
        assert (tenant.schema_name, ip) in gdpr_tasks._last_confirm_burst_alerted


@pytest.mark.django_db
class TestWindowAndCooldown:
    def test_lodges_outside_window_are_ignored(self, tenant):
        for _ in range(gdpr_tasks.DELETION_LODGE_BURST_THRESHOLD):
            _make_lodge(
                user=JasminUserFactory(),
                ip="9.9.9.9",
                age=gdpr_tasks.DELETION_BURST_WINDOW + datetime.timedelta(minutes=10),
            )

        with patch.object(gdpr_tasks, "mail_admins") as mock_mail:
            gdpr_tasks.alert_on_deletion_endpoint_bursts.call_local()
        mock_mail.assert_not_called()

    def test_cooldown_suppresses_second_alert(self, tenant):
        for _ in range(gdpr_tasks.DELETION_LODGE_BURST_THRESHOLD):
            _make_lodge(user=JasminUserFactory(), ip="9.9.9.9")

        with patch.object(gdpr_tasks, "mail_admins") as mock_mail:
            gdpr_tasks.alert_on_deletion_endpoint_bursts.call_local()
        mock_mail.assert_called_once()

        with patch.object(gdpr_tasks, "mail_admins") as mock_mail:
            gdpr_tasks.alert_on_deletion_endpoint_bursts.call_local()
        mock_mail.assert_not_called()
