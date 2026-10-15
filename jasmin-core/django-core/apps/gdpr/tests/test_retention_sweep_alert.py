"""The retention sweep emails the operator: blocked erasures per tenant at most
weekly, failed erasures per tenant at most daily, and a tenant whose sweep
raises through ``for_each_tenant``."""

from __future__ import annotations

from unittest import mock

import pytest
from django.core.cache import cache

from apps.gdpr.tasks import anonymise_long_cancelled_members

RUN_FOR_SCHEMA = "apps.gdpr.tasks._run_for_current_schema"


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
class TestRetentionSweepAlert:
    def test_blocked_erasures_alert_once_a_week(
        self, tenant, mailoutbox, django_capture_on_commit_callbacks
    ):
        with mock.patch(RUN_FOR_SCHEMA, return_value=(0, 2)):
            with django_capture_on_commit_callbacks(execute=True):
                anonymise_long_cancelled_members.call_local()
            first_run = len(mailoutbox)
            with django_capture_on_commit_callbacks(execute=True):
                anonymise_long_cancelled_members.call_local()

        assert first_run >= 1
        assert len(mailoutbox) == first_run
        assert all("2 ex-member erasure(s) blocked" in m.subject for m in mailoutbox)

    def test_nothing_blocked_sends_nothing(
        self, tenant, mailoutbox, django_capture_on_commit_callbacks
    ):
        with (
            mock.patch(RUN_FOR_SCHEMA, return_value=(3, 0)),
            django_capture_on_commit_callbacks(execute=True),
        ):
            anonymise_long_cancelled_members.call_local()

        assert mailoutbox == []

    def test_failed_erasures_alert_and_are_counted(
        self, tenant, mailoutbox, django_capture_on_commit_callbacks
    ):
        def two_failures(_cutoff, *, failed_member_ids):
            failed_member_ids.extend(["member-a", "member-b"])
            return (0, 0)

        with (
            mock.patch(RUN_FOR_SCHEMA, side_effect=two_failures),
            django_capture_on_commit_callbacks(execute=True),
        ):
            result = anonymise_long_cancelled_members.call_local()

        failed_mails = [
            m for m in mailoutbox if "2 ex-member erasure(s) failed" in m.subject
        ]
        assert failed_mails
        assert "member-a, member-b" in failed_mails[0].body
        assert result["failed"] == 2 * len(failed_mails)

    def test_a_purge_crash_keeps_the_blocked_alert_and_counts_the_tenant_as_failed(
        self, tenant, mailoutbox, django_capture_on_commit_callbacks
    ):
        with (
            mock.patch(RUN_FOR_SCHEMA, return_value=(0, 2)),
            mock.patch(
                "apps.gdpr.tasks._purge_files_kept_by_erasure",
                side_effect=RuntimeError("purge failed"),
            ),
            django_capture_on_commit_callbacks(execute=True),
        ):
            result = anonymise_long_cancelled_members.call_local()

        subjects = [m.subject for m in mailoutbox]
        assert any("2 ex-member erasure(s) blocked" in s for s in subjects)
        assert any(
            "gdpr.retention_sweep:" in s and "tenant(s) failed" in s for s in subjects
        )
        assert result["tenants_scanned"] == 0
        assert result["tenants_failed"] >= 1
