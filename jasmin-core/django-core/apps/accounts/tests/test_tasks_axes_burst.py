"""Tests for ``apps.accounts.tasks.alert_on_axes_bursts``.

Each test mutates the module-level ``_last_alerted`` dedup state, so
we clear it via an autouse fixture to keep the cases independent.
"""

from __future__ import annotations

import datetime
from unittest.mock import patch

import pytest
from axes.models import AccessAttempt
from django.utils import timezone

from apps.accounts import tasks as axes_tasks


@pytest.fixture(autouse=True)
def _reset_dedup_state():
    axes_tasks._last_alerted.clear()
    yield
    axes_tasks._last_alerted.clear()


def _attempt(
    ip: str,
    *,
    username: str = "test",
    user_agent: str = "ua",
    failures: int = 1,
    age: datetime.timedelta = datetime.timedelta(minutes=10),
):
    """Record an AccessAttempt with ``failures_since_start=failures``.

    django-axes upserts on the unique ``(username, ip, user_agent)``
    triple, so a real brute-force burst is ONE row whose
    ``failures_since_start`` counter ticks up — not N rows. We mirror
    that with ``update_or_create``.

    ``attempt_time`` is ``auto_now``, so we have to update() after the
    insert to set a deterministic time inside the test's BURST_WINDOW.
    """
    obj, _ = AccessAttempt.objects.update_or_create(
        ip_address=ip,
        user_agent=user_agent,
        username=username,
        defaults={
            "get_data": "",
            "post_data": "",
            "http_accept": "",
            "path_info": "/",
            "failures_since_start": failures,
        },
    )
    AccessAttempt.objects.filter(pk=obj.pk).update(attempt_time=timezone.now() - age)
    return obj


@pytest.mark.django_db
class TestAlertOnAxesBursts:
    def test_no_alert_below_threshold(self, tenant):
        _attempt("1.2.3.4", failures=axes_tasks.BURST_THRESHOLD - 1)

        with patch.object(axes_tasks, "mail_admins") as mock_mail:
            axes_tasks.alert_on_axes_bursts.call_local()

        mock_mail.assert_not_called()
        assert "1.2.3.4" not in axes_tasks._last_alerted

    def test_alerts_at_threshold(self, tenant):
        _attempt("1.2.3.4", failures=axes_tasks.BURST_THRESHOLD)

        with patch.object(axes_tasks, "mail_admins") as mock_mail:
            axes_tasks.alert_on_axes_bursts.call_local()

        mock_mail.assert_called_once()
        # Subject reports a count of 1 (one IP), body lists the IP+count.
        subject, body = mock_mail.call_args.args[0], mock_mail.call_args.args[1]
        assert "1 brute-force burst" in subject
        assert "1.2.3.4" in body
        assert str(axes_tasks.BURST_THRESHOLD) in body
        assert "1.2.3.4" in axes_tasks._last_alerted

    def test_attempts_outside_window_are_ignored(self, tenant):
        # In-window failures stay below threshold; old failures are on a
        # different (username, ip, ua) row so they don't merge.
        _attempt(
            "1.2.3.4",
            username="fresh",
            failures=axes_tasks.BURST_THRESHOLD - 1,
        )
        _attempt(
            "1.2.3.4",
            username="old",
            failures=5,
            age=axes_tasks.BURST_WINDOW + datetime.timedelta(minutes=5),
        )

        with patch.object(axes_tasks, "mail_admins") as mock_mail:
            axes_tasks.alert_on_axes_bursts.call_local()

        mock_mail.assert_not_called()

    def test_cooldown_suppresses_second_alert(self, tenant):
        _attempt("1.2.3.4", failures=axes_tasks.BURST_THRESHOLD)

        with patch.object(axes_tasks, "mail_admins") as mock_mail:
            axes_tasks.alert_on_axes_bursts.call_local()
            axes_tasks.alert_on_axes_bursts.call_local()

        # Second run sees the same burst but skips due to the per-IP
        # cooldown — only one email goes out.
        assert mock_mail.call_count == 1

    def test_separate_ips_each_alert_independently(self, tenant):
        _attempt("1.2.3.4", failures=axes_tasks.BURST_THRESHOLD)
        _attempt("5.6.7.8", failures=axes_tasks.BURST_THRESHOLD)

        with patch.object(axes_tasks, "mail_admins") as mock_mail:
            axes_tasks.alert_on_axes_bursts.call_local()

        # One email per task run, listing both bursts inside it.
        mock_mail.assert_called_once()
        body = mock_mail.call_args.args[1]
        assert "1.2.3.4" in body
        assert "5.6.7.8" in body
