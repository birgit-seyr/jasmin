"""Super-admin SupportTicketAdminViewSet: cross-tenant aggregation + tenant-name
resolution, status filtering, reply (super_admin author), status transitions, and
auth gating. Dispatched directly via APIRequestFactory (mirrors the ops-checklist
tests)."""

from __future__ import annotations

import pytest
from django_tenants.utils import schema_context
from rest_framework.test import force_authenticate

from apps.commissioning.tests.factories import JasminUserFactory
from apps.shared.support.admin_viewsets import SupportTicketAdminViewSet


def _mk(tenant_schema, subject="t"):
    with schema_context("public"):
        from apps.shared.support.models import SupportTicket

        return SupportTicket.objects.create(
            tenant_schema=tenant_schema,
            subject=subject,
            creator_id="C1",
            creator_name="C",
            creator_email="c@example.com",
            creator_roles=["office"],
        )


def _dispatch(actions, request, **kwargs):
    return SupportTicketAdminViewSet.as_view(actions)(request, **kwargs)


@pytest.mark.django_db
class TestAdminList:
    def test_aggregates_across_tenants_with_names(self, factory, super_admin):
        a = _mk("test_pytest", "alpha")
        b = _mk("zzz_unknown_tenant", "beta")
        request = factory.get("/api/super-admin/support-tickets/")
        force_authenticate(request, user=super_admin)
        resp = _dispatch({"get": "list"}, request)
        assert resp.status_code == 200
        results = resp.data["results"]
        by_id = {r["id"]: r for r in results}
        assert a.id in by_id and b.id in by_id
        # tenant_name from Tenant (test_pytest → "Test Farm"); unknown tenant
        # falls back to the schema string.
        assert by_id[a.id]["tenant_name"] == "Test Farm"
        assert by_id[b.id]["tenant_name"] == "zzz_unknown_tenant"

    def test_status_filter(self, factory, super_admin):
        _mk("test_pytest")  # status defaults to open
        request = factory.get("/api/super-admin/support-tickets/?status=closed")
        force_authenticate(request, user=super_admin)
        resp = _dispatch({"get": "list"}, request)
        assert resp.status_code == 200
        assert resp.data["count"] == 0

    def test_invalid_status_is_400(self, factory, super_admin):
        request = factory.get("/api/super-admin/support-tickets/?status=bogus")
        force_authenticate(request, user=super_admin)
        resp = _dispatch({"get": "list"}, request)
        assert resp.status_code == 400
        assert resp.data["code"] == "support.invalid_status"


@pytest.mark.django_db
class TestAdminAuth:
    def test_anonymous_rejected(self, factory, _tenant_schema):
        request = factory.get("/api/super-admin/support-tickets/")
        resp = _dispatch({"get": "list"}, request)
        assert resp.status_code in (401, 403)

    def test_non_super_admin_rejected(self, factory, tenant):
        regular = JasminUserFactory(roles=["office"])
        request = factory.get("/api/super-admin/support-tickets/")
        force_authenticate(request, user=regular)
        resp = _dispatch({"get": "list"}, request)
        assert resp.status_code == 403


@pytest.mark.django_db
class TestAdminReplyAndStatus:
    def test_super_admin_reply_appends_message(self, factory, super_admin):
        ticket = _mk("test_pytest")
        request = factory.post(
            f"/api/super-admin/support-tickets/{ticket.id}/reply/",
            {"body": "we are on it"},
            format="json",
        )
        force_authenticate(request, user=super_admin)
        resp = _dispatch({"post": "reply"}, request, pk=ticket.id)
        assert resp.status_code == 200
        last = resp.data["messages"][-1]
        assert last["author_kind"] == "super_admin"
        assert last["body"] == "we are on it"

    def test_set_status_resolved_stamps_resolved_at(self, factory, super_admin):
        ticket = _mk("test_pytest")
        request = factory.post(
            f"/api/super-admin/support-tickets/{ticket.id}/set-status/",
            {"status": "resolved"},
            format="json",
        )
        force_authenticate(request, user=super_admin)
        resp = _dispatch({"post": "set_status"}, request, pk=ticket.id)
        assert resp.status_code == 200
        assert resp.data["status"] == "resolved"
        with schema_context("public"):
            ticket.refresh_from_db()
        assert ticket.resolved_at is not None

    def test_retrieve_unknown_is_404(self, factory, super_admin):
        request = factory.get("/api/super-admin/support-tickets/NOPE/")
        force_authenticate(request, user=super_admin)
        resp = _dispatch({"get": "retrieve"}, request, pk="NOPE")
        assert resp.status_code == 404
        assert resp.data["code"] == "support.ticket_not_found"
