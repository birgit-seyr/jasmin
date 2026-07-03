"""Tests for ``MemberViewSet.emails`` — per-member EmailLog projection
powering the office UI's "Sent emails" modal.

Coverage:
  * happy path: returns this member's EmailLog rows, newest-first
  * scoping: rows for OTHER members never leak into this member's view
  * empty-email member returns []
  * permission gating: member role 403, anon 401/403
"""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.commissioning.tests.factories import MemberFactory
from apps.notifications.models import EmailLog


def _log(
    recipient: str,
    purpose: str,
    sent_at: datetime.datetime | None = None,
    status: str = "sent",
    subject: str = "x",
) -> EmailLog:
    return EmailLog.objects.create(
        recipient=recipient,
        subject=subject,
        template="t",
        purpose=purpose,
        status=status,
        sent_at=sent_at,
    )


def _url(member_id: str) -> str:
    return f"/api/commissioning/members/{member_id}/emails/"


@pytest.mark.django_db
class TestMemberEmailsAction:
    def test_returns_only_this_members_logs(self, tenant, api_client):
        target = MemberFactory(email="target@example.com")
        other = MemberFactory(email="other@example.com")
        _log(target.email, "accounts.application_approved")
        _log(target.email, "commissioning.invoice")
        _log(other.email, "accounts.invitation")  # noise

        response = api_client.get(_url(target.id))
        assert response.status_code == 200, response.content
        body = response.json()
        purposes = {row["purpose"] for row in body}
        assert purposes == {
            "accounts.application_approved",
            "commissioning.invoice",
        }
        assert len(body) == 2

    def test_rows_sorted_newest_first(self, tenant, api_client):
        member = MemberFactory(email="m@example.com")
        old = _log(member.email, "accounts.invitation")
        # Force created_at ordering: created_at uses auto_now_add, so
        # the second row is automatically newer.
        new = _log(member.email, "accounts.application_approved")

        response = api_client.get(_url(member.id))
        body = response.json()
        assert [row["id"] for row in body] == [new.id, old.id]

    def test_member_without_email_returns_empty_list(self, tenant, api_client):
        member = MemberFactory(email="")
        # Defensive: a stray blank-recipient EmailLog row must NOT match.
        _log("", "accounts.welcome_user")
        response = api_client.get(_url(member.id))
        assert response.status_code == 200
        assert response.json() == []

    def test_projects_audit_relevant_columns(self, tenant, api_client):
        member = MemberFactory(email="m@example.com")
        # ``created_at`` is auto_now_add (stamped at INSERT). Keep ``sent_at``
        # at/after it so the sent-after-created ordering holds.
        sent_at = timezone.now() + datetime.timedelta(seconds=1)
        _log(
            member.email,
            "accounts.application_approved",
            sent_at=sent_at,
            status="delivered",
            subject="Du bist drin",
        )
        response = api_client.get(_url(member.id))
        row = response.json()[0]
        assert set(row.keys()) == {
            "id",
            "purpose",
            "subject",
            "template",
            "status",
            "sent_at",
            "delivered_at",
            "created_at",
        }
        assert row["status"] == "delivered"
        assert row["subject"] == "Du bist drin"

    def test_member_role_forbidden(self, tenant, member_user):
        member = MemberFactory(email="m@example.com")
        client = APIClient()
        client.force_authenticate(user=member_user)
        response = client.get(_url(member.id))
        assert response.status_code in (401, 403)

    def test_anonymous_forbidden(self, tenant, anon_client):
        member = MemberFactory(email="m@example.com")
        response = anon_client.get(_url(member.id))
        assert response.status_code in (401, 403)
