"""Tests for ``views/ops_checklist.py`` — super-admin ops checklist.

``OpsChecklistItem`` / ``OpsChecklistRun`` live in the **public schema**
(``apps.shared.super_admin`` is in ``SHARED_APPS``), so the test fixture
creates rows under ``schema_context("public")`` and the view dispatches
the same way.

Items aren't created at runtime — they're seeded by a migration. To keep
the tests independent of whatever's seeded, each test creates its own
item under a unique ``kind`` and cleans up afterwards.
"""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.commissioning.tests.factories import JasminUserFactory
from apps.shared.super_admin.models import (
    OpsChecklistItem,
    OpsChecklistRun,
    SuperAdmin,
)
from apps.shared.super_admin.viewsets import OpsChecklistViewSet


@pytest.fixture
def super_admin(_tenant_schema):
    with schema_context("public"):
        admin, _ = SuperAdmin.objects.get_or_create(
            email="ops-tests@example.com",
            defaults={"first_name": "Ops", "last_name": "Tester"},
        )
    admin.is_super_admin = True
    admin.user_role = "super_admin"
    return admin


@pytest.fixture
def factory():
    return APIRequestFactory()


@pytest.fixture
def checklist_item(_tenant_schema):
    """A fresh OpsChecklistItem in the public schema, deleted on teardown.

    Uses ``kind="custom"`` (one of the documented choices) so it doesn't
    conflict with anything a migration might also seed under the same key.
    """
    with schema_context("public"):
        item = OpsChecklistItem.objects.create(
            kind="custom",
            title="Test rotation",
            description="Run-book notes for the rotation.",
            interval_days=30,
            is_active=True,
        )
    yield item
    with schema_context("public"):
        # Cascades to OpsChecklistRun rows.
        OpsChecklistItem.objects.filter(pk=item.pk).delete()


def _dispatch(actions, request, **url_kwargs):
    view = OpsChecklistViewSet.as_view(actions)
    return view(request, **url_kwargs)


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestList:
    def test_returns_seeded_item(self, factory, super_admin, checklist_item):
        request = factory.get("/ops-checklist/")
        force_authenticate(request, user=super_admin)
        response = _dispatch({"get": "list"}, request)

        assert response.status_code == 200
        ids = [item["id"] for item in response.data]
        assert checklist_item.id in ids

        entry = next(item for item in response.data if item["id"] == checklist_item.id)
        assert entry["kind"] == "custom"
        assert entry["title"] == "Test rotation"
        assert entry["interval_days"] == 30
        assert entry["last_run"] is None
        # An item that has never been run, with a 30-day interval, is
        # not overdue right after creation.
        assert entry["is_overdue"] is False


# ---------------------------------------------------------------------------
# Mark done
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMarkDone:
    def test_creates_run_and_returns_refreshed_item(
        self, factory, super_admin, checklist_item
    ):
        request = factory.post(
            f"/ops-checklist/{checklist_item.id}/mark-done/",
            {"notes": "Rotated key, restarted gunicorn, verified login."},
            format="json",
        )
        force_authenticate(request, user=super_admin)
        response = _dispatch({"post": "mark_done"}, request, pk=str(checklist_item.id))

        assert response.status_code == 200
        with schema_context("public"):
            runs = OpsChecklistRun.objects.filter(item=checklist_item)
            assert runs.count() == 1
            run = runs.first()
            assert run.notes == "Rotated key, restarted gunicorn, verified login."
            assert run.completed_by_id == super_admin.id

        # Returned payload reflects the new last_run.
        assert response.data["last_run"] is not None
        assert response.data["last_run"]["completed_by_email"] == super_admin.email

    def test_returns_404_for_unknown_item(self, factory, super_admin):
        request = factory.post("/ops-checklist/999999/mark-done/", {}, format="json")
        force_authenticate(request, user=super_admin)
        response = _dispatch({"post": "mark_done"}, request, pk="999999")

        assert response.status_code == 404

    def test_overdue_item_becomes_not_overdue_after_mark_done(
        self, factory, super_admin, _tenant_schema
    ):
        """``next_due_at`` is computed from the most recent run's
        ``completed_at``; marking done resets the clock."""
        with schema_context("public"):
            item = OpsChecklistItem.objects.create(
                kind="custom",
                title="Stale item",
                interval_days=1,
                is_active=True,
            )
            # Backdate created_at so the item is overdue right now.
            OpsChecklistItem.objects.filter(pk=item.pk).update(
                created_at=timezone.now() - datetime.timedelta(days=10)
            )
            item.refresh_from_db()
            assert item.is_overdue is True

        try:
            request = factory.post(
                f"/ops-checklist/{item.id}/mark-done/", {}, format="json"
            )
            force_authenticate(request, user=super_admin)
            response = _dispatch({"post": "mark_done"}, request, pk=str(item.id))

            assert response.status_code == 200
            assert response.data["is_overdue"] is False
        finally:
            with schema_context("public"):
                OpsChecklistItem.objects.filter(pk=item.pk).delete()


# ---------------------------------------------------------------------------
# Auth gating
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAuthGating:
    def test_anonymous_list_is_rejected(self, factory, _tenant_schema):
        request = factory.get("/ops-checklist/")
        response = _dispatch({"get": "list"}, request)
        assert response.status_code in (401, 403)

    def test_non_super_admin_is_rejected(self, factory, tenant):
        """Regular JasminUser (no ``is_super_admin`` attr) is forbidden."""
        regular_user = JasminUserFactory(roles=["office", "admin"])
        request = factory.get("/ops-checklist/")
        force_authenticate(request, user=regular_user)
        response = _dispatch({"get": "list"}, request)
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# run-rotation step-up gate (SEC-6)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRunRotationStepUp:
    """``run_rotation`` dispatches secret / DB-password regeneration and the
    mass email-credential clear — destructive platform-wide actions. They
    must be step-up gated like the backup trigger and role grants, so a
    stolen super-admin session can't fire them without a fresh password."""

    def test_run_rotation_without_step_up_is_rejected(
        self, factory, super_admin, checklist_item
    ):
        request = factory.post(
            f"/ops-checklist/{checklist_item.id}/run-rotation/", {}, format="json"
        )
        # Plain super-admin auth, NO step-up claim on the token.
        force_authenticate(request, user=super_admin)
        response = _dispatch(
            {"post": "run_rotation"}, request, pk=str(checklist_item.id)
        )

        assert response.status_code == 403
        # Distinguish the step-up gate from a generic forbidden — this is
        # the code the frontend interceptor branches on.
        assert response.data["code"] == "auth.step_up_required"

    def test_run_rotation_with_step_up_passes_gate(
        self, factory, super_admin, checklist_item
    ):
        """With a fresh step-up token the gate is satisfied, so the request
        reaches the view body. The ``custom`` kind isn't dispatchable, so it
        lands on the kind guard → 400. The 400 (not 403) is positive proof
        the step-up gate accepted us — without firing a real rotation."""
        from apps.commissioning.tests.conftest import make_step_up_token

        request = factory.post(
            f"/ops-checklist/{checklist_item.id}/run-rotation/", {}, format="json"
        )
        force_authenticate(
            request, user=super_admin, token=make_step_up_token(super_admin)
        )
        response = _dispatch(
            {"post": "run_rotation"}, request, pk=str(checklist_item.id)
        )

        assert response.status_code == 400
        assert not (
            response.status_code == 403
            and response.data.get("code") == "auth.step_up_required"
        ), "fresh step-up token was rejected — the gate did not accept us"
