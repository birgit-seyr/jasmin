"""``alert_operator``: an email to ``ADMINS`` once the transaction commits, at
most one per throttle window, never raising."""

from __future__ import annotations

from unittest import mock

import pytest
from django.core.cache import cache

from apps.shared.ops_alerts import alert_operator


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
class TestAlertOperator:
    def test_sends_once_the_transaction_commits(
        self, mailoutbox, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            alert_operator("Something to look at", "Details")
            assert mailoutbox == []

        assert len(mailoutbox) == 1
        assert mailoutbox[0].subject.endswith("[jasmin] Something to look at")
        assert mailoutbox[0].body == "Details"

    def test_a_throttled_alert_goes_out_once_per_window(
        self, mailoutbox, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            for _ in range(3):
                alert_operator(
                    "Repeated", "Details", throttle_key="repeat", throttle_seconds=60
                )

        assert len(mailoutbox) == 1

    def test_a_failed_send_is_swallowed(self, django_capture_on_commit_callbacks):
        with (
            mock.patch(
                "apps.shared.ops_alerts.mail_admins",
                side_effect=ConnectionError("smtp down"),
            ),
            django_capture_on_commit_callbacks(execute=True),
        ):
            alert_operator("Subject", "Body")

    def test_a_cache_error_on_the_throttle_still_sends(
        self, mailoutbox, django_capture_on_commit_callbacks
    ):
        with (
            mock.patch(
                "apps.shared.ops_alerts.cache.add",
                side_effect=ConnectionError("redis down"),
            ),
            django_capture_on_commit_callbacks(execute=True),
        ):
            alert_operator("Subject", "Body", throttle_key="key", throttle_seconds=60)

        assert len(mailoutbox) == 1
