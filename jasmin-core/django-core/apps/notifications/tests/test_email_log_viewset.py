"""The email-log API: its filters scope the list, and only the list.

``recipient`` / ``purpose`` / ``status`` narrow the audit list the office page
renders. The detail route addresses one log row by id, so the same parameters
left on the URL must not hide it.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.commissioning.tests.factories import JasminUserFactory
from apps.notifications.models import EmailLog

LIST_URL = reverse("email-log-list")


def _log(*, recipient: str = "member@example.org", status_value: str = "sent"):
    return EmailLog.objects.create(
        recipient=recipient,
        subject="Subject",
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
class TestEmailLogListFilters:
    def test_status_filter_narrows_the_list(self, office_client, tenant):
        _log(status_value="sent")
        failed = _log(status_value="failed", recipient="other@example.org")

        resp = office_client.get(LIST_URL, {"status": "failed"})
        assert resp.status_code == status.HTTP_200_OK
        assert [row["id"] for row in resp.data] == [failed.id]

    def test_unknown_status_is_refused(self, office_client, tenant):
        resp = office_client.get(LIST_URL, {"status": "nope"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "query.invalid_param"
        assert resp.data["field"] == "status"


@pytest.mark.django_db
class TestEmailLogDetailIgnoresListFilters:
    def test_detail_reaches_a_row_the_filter_excludes(self, office_client, tenant):
        log = _log(status_value="sent")
        resp = office_client.get(
            reverse("email-log-detail", kwargs={"pk": log.pk}),
            {"status": "failed", "recipient": "nobody@example.org"},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["id"] == log.id

    def test_detail_does_not_validate_a_filter_it_never_reads(
        self, office_client, tenant
    ):
        """An unknown status 400s the LIST (it would otherwise answer empty for
        a typo). The detail route filters by nothing, so it has no reason to
        refuse the call."""
        log = _log()
        resp = office_client.get(
            reverse("email-log-detail", kwargs={"pk": log.pk}), {"status": "nope"}
        )
        assert resp.status_code == status.HTTP_200_OK
