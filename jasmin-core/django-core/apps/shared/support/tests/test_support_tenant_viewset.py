"""Tenant-facing SupportTicketViewSet: role gating, tenant isolation, the
first-message-on-create, identity spoofing, context sanitization, visibility,
reply, throttling, and the prod-only admin email."""

from __future__ import annotations

from unittest import mock

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.commissioning.tests.factories import JasminUserFactory
from apps.shared.support.models import SupportTicket

LIST_URL = "/api/support/tickets/"


def _detail_url(pk):
    return f"/api/support/tickets/{pk}/"


def _reply_url(pk):
    return f"/api/support/tickets/{pk}/reply/"


def _authed(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _mk_ticket(tenant_schema, creator_id, subject="t"):
    return SupportTicket.objects.create(
        tenant_schema=tenant_schema,
        subject=subject,
        creator_id=creator_id,
        creator_name="X",
        creator_email="x@example.com",
        creator_roles=[],
    )


@pytest.mark.django_db
class TestCreate:
    def test_office_creates_ticket_with_first_message(self, api_client, user):
        resp = api_client.post(
            LIST_URL,
            {"subject": "Login broken", "description": "I cannot log in."},
            format="json",
        )
        assert resp.status_code == 201, resp.data
        assert resp.data["subject"] == "Login broken"
        assert resp.data["status"] == "open"
        # The description becomes the first (staff-authored) message.
        assert len(resp.data["messages"]) == 1
        msg = resp.data["messages"][0]
        assert msg["author_kind"] == "staff"
        assert msg["body"] == "I cannot log in."
        ticket = SupportTicket.objects.get(pk=resp.data["id"])
        assert ticket.tenant_schema == "test_pytest"
        assert ticket.creator_id == str(user.id)
        assert ticket.creator_email == (user.email or "")

    def test_member_cannot_create(self, member_user):
        resp = _authed(member_user).post(
            LIST_URL, {"subject": "x", "description": "y"}, format="json"
        )
        assert resp.status_code == 403

    def test_customer_cannot_create(self, tenant):
        customer = JasminUserFactory(roles=["customer"])
        resp = _authed(customer).post(
            LIST_URL, {"subject": "x", "description": "y"}, format="json"
        )
        assert resp.status_code == 403

    def test_anonymous_cannot_create(self, anon_client):
        resp = anon_client.post(
            LIST_URL, {"subject": "x", "description": "y"}, format="json"
        )
        assert resp.status_code in (401, 403)

    def test_client_cannot_spoof_identity_or_status(self, api_client, user):
        resp = api_client.post(
            LIST_URL,
            {
                "subject": "x",
                "description": "y",
                "tenant_schema": "other_tenant",
                "creator_email": "evil@example.com",
                "creator_id": "SPOOFED",
                "status": "closed",
            },
            format="json",
        )
        assert resp.status_code == 201
        ticket = SupportTicket.objects.get(pk=resp.data["id"])
        assert ticket.tenant_schema == "test_pytest"
        assert ticket.creator_id == str(user.id)
        assert ticket.creator_email == (user.email or "")
        assert ticket.status == "open"

    def test_context_is_sanitized(self, api_client):
        resp = api_client.post(
            LIST_URL,
            {
                "subject": "x",
                "description": "y",
                "context": {
                    "page_path": "/members/42?st=secrettoken#frag",
                    "user_agent": "UA/1.0",
                    "evil_key": "dropme",
                },
            },
            format="json",
        )
        assert resp.status_code == 201
        ctx = SupportTicket.objects.get(pk=resp.data["id"]).context
        assert ctx["page_path"] == "/members/42"  # query + fragment stripped
        assert ctx["user_agent"] == "UA/1.0"
        assert "evil_key" not in ctx


@pytest.mark.django_db
class TestTenantIsolation:
    def test_list_excludes_other_tenant(self, api_client, user):
        mine = _mk_ticket("test_pytest", str(user.id))
        other = _mk_ticket("other_tenant", "ZZZ")
        resp = api_client.get(LIST_URL)
        assert resp.status_code == 200
        ids = [t["id"] for t in resp.data]
        assert mine.id in ids
        assert other.id not in ids

    def test_retrieve_other_tenant_is_404(self, api_client):
        other = _mk_ticket("other_tenant", "ZZZ")
        resp = api_client.get(_detail_url(other.id))
        assert resp.status_code == 404

    def test_reply_to_other_tenant_is_404(self, api_client):
        other = _mk_ticket("other_tenant", "ZZZ")
        resp = api_client.post(_reply_url(other.id), {"body": "hi"}, format="json")
        assert resp.status_code == 404


@pytest.mark.django_db
class TestVisibility:
    def test_staff_sees_only_own(self, tenant):
        staff = JasminUserFactory(roles=["staff"])
        other = JasminUserFactory(roles=["staff"])
        mine = _mk_ticket("test_pytest", str(staff.id))
        theirs = _mk_ticket("test_pytest", str(other.id))
        resp = _authed(staff).get(LIST_URL)
        assert resp.status_code == 200
        ids = [t["id"] for t in resp.data]
        assert mine.id in ids
        assert theirs.id not in ids

    def test_office_sees_all_tenant_tickets(self, tenant, user):
        staff = JasminUserFactory(roles=["staff"])
        a = _mk_ticket("test_pytest", str(user.id))
        b = _mk_ticket("test_pytest", str(staff.id))
        resp = _authed(user).get(LIST_URL)  # ``user`` is office
        assert resp.status_code == 200
        ids = [t["id"] for t in resp.data]
        assert a.id in ids and b.id in ids


@pytest.mark.django_db
class TestReply:
    def _create(self, api_client):
        return api_client.post(
            LIST_URL, {"subject": "s", "description": "d"}, format="json"
        ).data["id"]

    def test_reply_appends_staff_message(self, api_client):
        tid = self._create(api_client)
        resp = api_client.post(_reply_url(tid), {"body": "more info"}, format="json")
        assert resp.status_code == 200
        assert len(resp.data["messages"]) == 2
        assert resp.data["messages"][-1]["author_kind"] == "staff"
        assert resp.data["messages"][-1]["body"] == "more info"

    def test_whitespace_reply_rejected(self, api_client):
        tid = self._create(api_client)
        resp = api_client.post(_reply_url(tid), {"body": "   "}, format="json")
        assert resp.status_code == 400
        assert resp.data["code"] == "support.reply_empty"


@pytest.mark.django_db
class TestAdminEmail:
    def test_no_email_under_debug(self, api_client):
        # pytest runs with DEBUG=True → the prod-only alert must NOT fire.
        with mock.patch("apps.shared.support.viewsets.mail_admins") as m:
            api_client.post(
                LIST_URL, {"subject": "s", "description": "d"}, format="json"
            )
        m.assert_not_called()

    @override_settings(DEBUG=False)
    def test_email_sent_when_not_debug(
        self, api_client, user, django_capture_on_commit_callbacks
    ):
        with mock.patch("apps.shared.support.viewsets.mail_admins") as m:
            with django_capture_on_commit_callbacks(execute=True):
                api_client.post(
                    LIST_URL,
                    {"subject": "Secret member data", "description": "PII in body"},
                    format="json",
                )
        m.assert_called_once()
        # Minimal body — the free-text description must NOT leak into the alert.
        _subject, body = m.call_args.args[:2]
        assert "PII in body" not in body


@pytest.mark.django_db
class TestThrottle:
    def test_create_is_rate_limited(self, api_client):
        # support_ticket_create = 10/hour → the 11th call is throttled.
        statuses = [
            api_client.post(
                LIST_URL, {"subject": f"s{i}", "description": "d"}, format="json"
            ).status_code
            for i in range(11)
        ]
        assert statuses[:10] == [201] * 10
        assert statuses[10] == 429
