"""The ``suppressed`` EmailLog status: a send that onboarding mode blocked.

Suppressed rows are pruned after the retention window like healthy traffic, and
the email log API accepts ``suppressed`` as a status filter.
"""

from __future__ import annotations

import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.commissioning.tests.factories import JasminUserFactory
from apps.notifications.models import EmailLog
from apps.notifications.tasks import (
    NOTIFICATION_LOG_RETENTION_DAYS,
    cleanup_stale_email_logs,
)


def _log(status_value: str, *, recipient: str) -> EmailLog:
    return EmailLog.objects.create(
        recipient=recipient,
        subject="",
        template="commissioning.member_cancelled",
        purpose="commissioning.member_cancelled",
        status=status_value,
    )


@pytest.fixture()
def office_client(tenant):
    client = APIClient()
    client.force_authenticate(user=JasminUserFactory(roles=["office"]))
    return client


@pytest.mark.django_db
class TestCleanup:
    def test_old_suppressed_rows_are_pruned_like_sent_rows(self, tenant):
        old_suppressed = _log("suppressed", recipient="old-suppressed@example.org")
        old_sent = _log("sent", recipient="old-sent@example.org")
        old_failed = _log("failed", recipient="old-failed@example.org")
        _log("suppressed", recipient="recent-suppressed@example.org")
        # Relative to the real clock, like the cleanup's own cutoff.
        EmailLog.objects.filter(
            pk__in=[old_suppressed.pk, old_sent.pk, old_failed.pk]
        ).update(
            created_at=timezone.now()
            - datetime.timedelta(days=NOTIFICATION_LOG_RETENTION_DAYS + 1)
        )

        cleanup_stale_email_logs.call_local()

        assert set(EmailLog.objects.values_list("recipient", flat=True)) == {
            "old-failed@example.org",
            "recent-suppressed@example.org",
        }


@pytest.mark.django_db
class TestStatusFilter:
    def test_suppressed_is_an_accepted_status(self, office_client):
        _log("suppressed", recipient="suppressed@example.org")
        _log("sent", recipient="sent@example.org")

        resp = office_client.get(reverse("email-log-list"), {"status": "suppressed"})

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert [(row["recipient"], row["status"]) for row in resp.data] == [
            ("suppressed@example.org", "suppressed")
        ]

    def test_an_unknown_status_is_refused(self, office_client):
        resp = office_client.get(reverse("email-log-list"), {"status": "skipped"})

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
