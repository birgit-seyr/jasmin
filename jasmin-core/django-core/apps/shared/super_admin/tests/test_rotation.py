"""Tests for the super-admin rotation service + viewset action.

Two layers:

  * ``TestRotationService`` — pure unit tests for the per-kind
    implementations in ``services/rotation.py``. Asserts the shape of
    the ``RotationResult`` and (for ``rotate_email_creds``) the
    side-effects on ``TenantEmailConfig``.

  * ``TestRunRotationView`` — exercises the new
    ``POST /ops-checklist/<pk>/run-rotation/`` action via the same
    pattern the existing ``TestMarkDone`` tests use: a public-schema
    fixture item, ``force_authenticate`` as super-admin,
    ``_dispatch``.

We do NOT lock the EXACT generated-secret value (it's random by
design); we only assert that it's a non-empty string of plausible
length.
"""

from __future__ import annotations

import pytest
from django_tenants.utils import schema_context
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.commissioning.tests.conftest import make_step_up_token
from apps.commissioning.tests.factories import JasminUserFactory
from apps.shared.super_admin.models import OpsChecklistItem, SuperAdmin
from apps.shared.super_admin.services.rotation import (
    DISPATCHABLE_KINDS,
    UnknownRotationKind,
    rotate,
)
from apps.shared.super_admin.viewsets import OpsChecklistViewSet
from apps.shared.tenants.models import Tenant, TenantEmailConfig

# ---------------------------------------------------------------------------
# Fixtures (mirror test_ops_checklist_views.py shape)
# ---------------------------------------------------------------------------


@pytest.fixture
def super_admin(_tenant_schema):
    with schema_context("public"):
        admin, _ = SuperAdmin.objects.get_or_create(
            email="rotation-tests@example.com",
            defaults={"first_name": "Rot", "last_name": "Tester"},
        )
    admin.is_super_admin = True
    admin.user_role = "super_admin"
    return admin


@pytest.fixture
def factory():
    return APIRequestFactory()


@pytest.fixture
def rotation_item(_tenant_schema):
    """A checklist row with a real rotation kind so the viewset action
    dispatches into the service. ``rotate_django_secret`` is the
    cheapest one to test (no DB side-effects)."""
    with schema_context("public"):
        item = OpsChecklistItem.objects.create(
            kind="rotate_django_secret",
            title="Test: rotate Django secret",
            description="",
            interval_days=180,
            is_active=True,
        )
    yield item
    with schema_context("public"):
        OpsChecklistItem.objects.filter(pk=item.pk).delete()


@pytest.fixture
def email_creds_item(_tenant_schema):
    with schema_context("public"):
        item = OpsChecklistItem.objects.create(
            kind="rotate_email_creds",
            title="Test: rotate email creds",
            description="",
            interval_days=365,
            is_active=True,
        )
    yield item
    with schema_context("public"):
        OpsChecklistItem.objects.filter(pk=item.pk).delete()


@pytest.fixture
def non_rotation_item(_tenant_schema):
    with schema_context("public"):
        item = OpsChecklistItem.objects.create(
            kind="restore_drill",
            title="Test: restore drill (not a rotation)",
            description="",
            interval_days=90,
            is_active=True,
        )
    yield item
    with schema_context("public"):
        OpsChecklistItem.objects.filter(pk=item.pk).delete()


def _dispatch(actions, request, **url_kwargs):
    view = OpsChecklistViewSet.as_view(actions)
    return view(request, **url_kwargs)


# ---------------------------------------------------------------------------
# Service layer
# ---------------------------------------------------------------------------


class TestRotationService:
    def test_django_secret_returns_a_long_random_string(self):
        result = rotate("rotate_django_secret")
        assert result.kind == "rotate_django_secret"
        assert isinstance(result.generated_secret, str)
        # ``secrets.token_urlsafe(50)`` produces ~67-char base64 strings.
        assert len(result.generated_secret) >= 50
        assert result.instructions
        assert "DJANGO_SECRET_KEY" in result.instructions
        assert result.items_affected == 0

    def test_django_secret_is_fresh_each_call(self):
        a = rotate("rotate_django_secret").generated_secret
        b = rotate("rotate_django_secret").generated_secret
        assert a != b, "Each rotation must produce a fresh secret."

    def test_db_password_returns_alter_user_sql(self):
        result = rotate("rotate_db_password")
        assert result.generated_secret
        assert "ALTER USER" in result.extras["alter_sql"]
        assert result.generated_secret in result.extras["alter_sql"]
        assert "Postgres" in result.instructions

    def test_bunny_token_is_runbook_only(self):
        result = rotate("rotate_bunny_token")
        assert result.generated_secret is None
        assert result.items_affected == 0
        assert "BunnyCDN" in result.instructions

    def test_unknown_kind_raises(self):
        with pytest.raises(UnknownRotationKind):
            rotate("rotate_nonsense")

    def test_dispatchable_kinds_includes_the_four(self):
        # Locks the contract the frontend's ROTATION_KINDS set mirrors.
        assert DISPATCHABLE_KINDS == frozenset(
            {
                "rotate_django_secret",
                "rotate_db_password",
                "rotate_bunny_token",
                "rotate_email_creds",
            }
        )


@pytest.mark.django_db
class TestRotateEmailCredsSideEffects:
    """``rotate_email_creds`` is the only kind that mutates DB state.
    The other three only generate or document."""

    def _make_tenant_with_smtp(self, schema_name: str, password: str):
        # rotate_email_creds works purely on the public ``TenantEmailConfig``
        # rows (``_rotate_email_creds`` does ``TenantEmailConfig.objects
        # .filter(...)`` — no per-tenant schema switching), so we only need a
        # Tenant + config row, NOT a provisioned schema. ``auto_create_schema=
        # False`` skips the DDL — and the matching ``DROP SCHEMA`` on cleanup,
        # which fails inside the test transaction with "auth_permission has
        # pending trigger events". The transaction rolls the rows back, so no
        # explicit teardown is needed.
        with schema_context("public"):
            tenant = Tenant(schema_name=schema_name, name=schema_name)
            tenant.auto_create_schema = False
            tenant.save()
            config = TenantEmailConfig.objects.create(
                tenant=tenant, smtp_password=password, is_verified=True
            )
        return tenant, config

    def test_dry_run_does_not_clear(self, _tenant_schema):
        _tenant, config = self._make_tenant_with_smtp(
            "rotation_test_dryrun", "original-pw"
        )
        result = rotate("rotate_email_creds", dry_run=True)
        assert result.items_affected >= 1
        config.refresh_from_db()
        assert config.smtp_password == "original-pw"
        assert config.is_verified is True

    def test_real_run_clears_and_marks_unverified(self, _tenant_schema):
        _tenant, config = self._make_tenant_with_smtp(
            "rotation_test_real", "original-pw"
        )
        result = rotate("rotate_email_creds", dry_run=False)
        assert result.items_affected >= 1
        config.refresh_from_db()
        assert config.smtp_password == ""
        assert config.is_verified is False


# ---------------------------------------------------------------------------
# Viewset action: POST /ops-checklist/<pk>/run-rotation/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRunRotationView:
    def test_runs_rotation_and_returns_secret(
        self, factory, super_admin, rotation_item
    ):
        request = factory.post(
            f"/ops-checklist/{rotation_item.id}/run-rotation/",
            {},
            format="json",
        )
        # run_rotation is step-up gated (destructive rotation) — give the
        # super-admin a fresh step-up claim so the request reaches the body.
        force_authenticate(
            request, user=super_admin, token=make_step_up_token(super_admin)
        )
        response = _dispatch(
            {"post": "run_rotation"}, request, pk=str(rotation_item.id)
        )

        assert response.status_code == 200
        body = response.data
        assert body["kind"] == "rotate_django_secret"
        assert body["generated_secret"]
        assert "DJANGO_SECRET_KEY" in body["instructions"]
        assert body["items_affected"] == 0

    def test_returns_404_for_unknown_item(self, factory, super_admin):
        request = factory.post("/ops-checklist/999999/run-rotation/", {})
        force_authenticate(
            request, user=super_admin, token=make_step_up_token(super_admin)
        )
        response = _dispatch({"post": "run_rotation"}, request, pk="999999")
        assert response.status_code == 404

    def test_returns_400_for_non_rotation_kind(
        self, factory, super_admin, non_rotation_item
    ):
        """Items like ``restore_drill`` aren't runnable rotations — the
        view must reject the request with a clear error so the
        frontend doesn't surface a confusing "success" toast."""
        request = factory.post(
            f"/ops-checklist/{non_rotation_item.id}/run-rotation/", {}
        )
        force_authenticate(
            request, user=super_admin, token=make_step_up_token(super_admin)
        )
        response = _dispatch(
            {"post": "run_rotation"}, request, pk=str(non_rotation_item.id)
        )
        assert response.status_code == 400
        assert "not a runnable rotation" in response.data["message"]

    def test_anonymous_request_is_rejected(
        self, factory, _tenant_schema, rotation_item
    ):
        request = factory.post(f"/ops-checklist/{rotation_item.id}/run-rotation/", {})
        response = _dispatch(
            {"post": "run_rotation"}, request, pk=str(rotation_item.id)
        )
        # Either 401 (auth required) or 403 (perm denied) is acceptable
        # — both prove the gate held.
        assert response.status_code in (401, 403)

    def test_non_super_admin_user_is_rejected(
        self, factory, _tenant_schema, rotation_item, tenant
    ):
        regular_user = JasminUserFactory()
        request = factory.post(f"/ops-checklist/{rotation_item.id}/run-rotation/", {})
        force_authenticate(request, user=regular_user)
        response = _dispatch(
            {"post": "run_rotation"}, request, pk=str(rotation_item.id)
        )
        assert response.status_code in (401, 403)
