"""Tests for :class:`TenantManagementViewSet` (super-admin tenant CRUD).

Why direct viewset dispatch instead of HTTP
-------------------------------------------
These endpoints live under ``PUBLIC_SCHEMA_URLCONF`` (= ``config.public_urls``),
so a normal ``APIClient.get("/api/super-admin/tenants/")`` against
``testserver`` would route through ``ROOT_URLCONF`` (= ``config.tenant_urls``)
and 404 — the super-admin URLs aren't mounted on tenant hosts.

Standing up a separate "public-host" Domain row plus middleware-switching
machinery just to exercise the viewset is overkill for unit-level coverage.
Instead we use ``APIRequestFactory + force_authenticate + viewset.as_view``,
which dispatches the action directly and skips both URL routing and
``TenantMainMiddleware``. The viewset itself enters the right schema with
``schema_context("public" | tenant_schema)`` inside each method, so callers
don't need to be on a particular schema.

Auth side-step: ``IsSuperAdmin`` checks ``request.user.is_super_admin``
(a JWT claim that ``SuperAdminJWTAuthentication.get_user`` normally stamps
onto the resolved user). We create a real ``SuperAdmin`` row in the public
schema, set ``is_super_admin=True`` on the instance, and pass it via
``force_authenticate`` — same end state as the JWT path, no token round-trip.
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, ProgrammingError
from django_tenants.utils import schema_context
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.models import JasminUser
from apps.commissioning.tests.conftest import make_step_up_token
from apps.commissioning.tests.factories import JasminUserFactory
from apps.shared.super_admin.models import SuperAdmin
from apps.shared.super_admin.viewsets import TenantManagementViewSet

# Satisfies AUTH_PASSWORD_VALIDATORS (12-char min + zxcvbn + common/numeric).
# The create / create_admin / create_user paths now enforce that policy
# (TEN-5), so any payload that should reach the action body needs a strong one.
_STRONG_PW = "9xKqP2mwLvZt7Rdn"


@pytest.fixture
def super_admin(_tenant_schema):
    """A ``SuperAdmin`` row in the public schema with the JWT claim flag set.

    ``email`` is unique per test run via the test name, so parallel tests
    don't collide on the ``email`` UNIQUE constraint when one fixture
    invocation hasn't been rolled back before the next starts.
    """
    with schema_context("public"):
        admin, _ = SuperAdmin.objects.get_or_create(
            email="super-admin-tests@example.com",
            defaults={"first_name": "Super", "last_name": "Tester"},
        )
    # IsSuperAdmin reads this attribute, not a DB column.
    admin.is_super_admin = True
    admin.user_role = "super_admin"
    return admin


@pytest.fixture
def factory():
    return APIRequestFactory()


def _dispatch(actions: dict, request, **url_kwargs):
    """Build a viewset view from an action map and invoke it."""
    view = TenantManagementViewSet.as_view(actions)
    return view(request, **url_kwargs)


# ---------------------------------------------------------------------------
# Auth / permission gating
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAuthGating:
    def test_anonymous_request_is_rejected(self, factory, tenant):
        """No credentials → IsSuperAdmin denies (401 or 403, not 200)."""
        request = factory.get("/tenants/")
        response = _dispatch({"get": "list"}, request)
        assert response.status_code in (401, 403)

    def test_non_super_admin_is_rejected(self, factory, tenant):
        """A regular JasminUser (no ``is_super_admin`` attr) is forbidden."""
        regular_user = JasminUserFactory(roles=["office", "admin"])
        request = factory.get("/tenants/")
        force_authenticate(request, user=regular_user)
        response = _dispatch({"get": "list"}, request)
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# list / retrieve / partial_update
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestListRetrieveUpdate:
    def test_list_returns_seeded_test_tenant(self, factory, tenant, super_admin):
        request = factory.get("/tenants/")
        force_authenticate(request, user=super_admin)
        response = _dispatch({"get": "list"}, request)

        assert response.status_code == 200
        schema_names = {entry["schema_name"] for entry in response.data}
        assert tenant.schema_name in schema_names

    def test_list_computes_user_count_by_default(self, factory, tenant, super_admin):
        """Default behaviour is unchanged — each tenant carries its exact
        (cross-schema) user count, which the super-admin dashboard renders."""
        request = factory.get("/tenants/")
        force_authenticate(request, user=super_admin)
        response = _dispatch({"get": "list"}, request)

        assert response.status_code == 200
        entry = next(e for e in response.data if e["schema_name"] == tenant.schema_name)
        assert isinstance(entry["user_count"], int)
        # Domain resolved from the single prefetch, not a per-tenant query.
        assert "domain" in entry

    def test_list_skips_user_count_when_opted_out(self, factory, tenant, super_admin):
        """``include_user_count=false`` drops the per-tenant search_path switch
        + COUNT; user_count comes back null while the roster (and the
        prefetched domain) are still returned."""
        request = factory.get("/tenants/", {"include_user_count": "false"})
        force_authenticate(request, user=super_admin)
        response = _dispatch({"get": "list"}, request)

        assert response.status_code == 200
        entry = next(e for e in response.data if e["schema_name"] == tenant.schema_name)
        assert entry["user_count"] is None
        assert "domain" in entry

    def test_retrieve_returns_tenant_details(self, factory, tenant, super_admin):
        request = factory.get(f"/tenants/{tenant.id}/")
        force_authenticate(request, user=super_admin)
        response = _dispatch({"get": "retrieve"}, request, pk=tenant.id)

        assert response.status_code == 200
        assert response.data["id"] == tenant.id
        assert response.data["schema_name"] == tenant.schema_name
        # ``domains`` is serialized as a list of {domain, is_primary} dicts.
        # Both ``pytest.localhost`` and ``testserver`` are seeded in
        # conftest; which one ends up ``is_primary=True`` depends on
        # django-tenants' DomainMixin auto-promotion (it defaults to
        # True and demotes the previous primary on save), so just check
        # the domain is present and exactly one row is marked primary.
        domain_names = {d["domain"] for d in response.data["domains"]}
        assert "pytest.localhost" in domain_names
        assert sum(1 for d in response.data["domains"] if d["is_primary"]) == 1

    def test_retrieve_unknown_tenant_returns_404(self, factory, tenant, super_admin):
        request = factory.get("/tenants/nonexistent99/")
        force_authenticate(request, user=super_admin)
        response = _dispatch({"get": "retrieve"}, request, pk="nonexistent99")

        assert response.status_code == 404
        assert "not found" in response.data["message"].lower()

    def test_partial_update_writes_allowed_fields(self, factory, tenant, super_admin):
        original_name = tenant.name
        try:
            request = factory.patch(
                f"/tenants/{tenant.id}/",
                {"name": "Renamed Test Farm", "description": "from-test"},
                format="json",
            )
            force_authenticate(request, user=super_admin)
            response = _dispatch({"patch": "partial_update"}, request, pk=tenant.id)

            assert response.status_code == 200
            assert response.data["name"] == "Renamed Test Farm"

            with schema_context("public"):
                from apps.shared.tenants.models import Tenant

                refreshed = Tenant.objects.get(id=tenant.id)
                assert refreshed.name == "Renamed Test Farm"
                assert refreshed.description == "from-test"
        finally:
            # Test_pytest tenant is session-scoped; reset the fields so other
            # tests see the original values.
            with schema_context("public"):
                from apps.shared.tenants.models import Tenant

                Tenant.objects.filter(id=tenant.id).update(
                    name=original_name, description=""
                )

    def test_partial_update_is_active_requires_step_up(
        self, factory, tenant, super_admin
    ):
        """TEN-7: flipping the is_active kill-switch needs a fresh step-up claim
        (a name-only PATCH, above, does not)."""
        request = factory.patch(
            f"/tenants/{tenant.id}/",
            {"is_active": False},
            format="json",
        )
        force_authenticate(request, user=super_admin)  # no step-up token
        response = _dispatch({"patch": "partial_update"}, request, pk=tenant.id)

        assert response.status_code == 403
        assert response.data["code"] == "auth.step_up_required"
        # Refused before any write — the tenant stays active.
        with schema_context("public"):
            from apps.shared.tenants.models import Tenant

            assert Tenant.objects.get(id=tenant.id).is_active


# ---------------------------------------------------------------------------
# Public schema is not a manageable tenant
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPublicSchemaExcluded:
    """The ``public`` schema is the platform itself, not a tenant. It must
    never appear in the tenant roster (no row, no count, no Details page)
    nor be retrievable / mutable through this viewset."""

    def _ensure_public_tenant(self):
        from apps.shared.tenants.models import Tenant

        with schema_context("public"):
            existing = Tenant.objects.filter(schema_name="public").first()
            if existing is not None:
                return existing.id
            # Create the row WITHOUT touching the (already-existing) schema.
            public = Tenant(schema_name="public", name="Platform Public")
            public.auto_create_schema = False
            public.save()
            return public.id

    def test_list_excludes_public_schema(self, factory, tenant, super_admin):
        self._ensure_public_tenant()

        request = factory.get("/tenants/")
        force_authenticate(request, user=super_admin)
        response = _dispatch({"get": "list"}, request)

        assert response.status_code == 200
        schema_names = {entry["schema_name"] for entry in response.data}
        assert "public" not in schema_names
        # The real tenant is still listed — the exclude is surgical.
        assert tenant.schema_name in schema_names

    def test_retrieve_public_schema_returns_404(self, factory, tenant, super_admin):
        public_id = self._ensure_public_tenant()

        request = factory.get(f"/tenants/{public_id}/")
        force_authenticate(request, user=super_admin)
        response = _dispatch({"get": "retrieve"}, request, pk=public_id)

        assert response.status_code == 404

    def test_nested_action_on_public_schema_returns_404(
        self, factory, tenant, super_admin
    ):
        """Nested actions (users / create-admin / ...) must also reject a
        known public id — defense-in-depth so the platform schema can never
        be operated on as if it were a tenant (e.g. creating a user there)."""
        public_id = self._ensure_public_tenant()

        request = factory.get(f"/tenants/{public_id}/users/")
        force_authenticate(request, user=super_admin)
        response = _dispatch({"get": "users"}, request, pk=public_id)

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Input validation on create / create-admin / create-user
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCreateValidation:
    """We don't exercise the happy path of ``create`` — provisioning a real
    tenant runs full migrations on a new schema and would balloon CI time.
    The validation branches are what catch operator typos, so cover those."""

    def test_create_requires_schema_name(self, factory, tenant, super_admin):
        request = factory.post(
            "/tenants/",
            {"name": "X", "domain": "x.example.com"},
            format="json",
        )
        force_authenticate(
            request, user=super_admin, token=make_step_up_token(super_admin)
        )
        response = _dispatch({"post": "create"}, request)

        assert response.status_code == 400
        # Now a canonical DRF serializer-validation body: the field name lives
        # in ``details`` (and ``field``), not in the generic ``message``.
        assert response.data["code"] == "validation_error"
        assert "schema_name" in response.data["details"]

    def test_create_requires_admin_credentials(self, factory, tenant, super_admin):
        request = factory.post(
            "/tenants/",
            {
                "schema_name": "newtenant",
                "name": "X",
                "domain": "x.example.com",
            },
            format="json",
        )
        force_authenticate(
            request, user=super_admin, token=make_step_up_token(super_admin)
        )
        response = _dispatch({"post": "create"}, request)

        assert response.status_code == 400
        # admin_email + admin_password both missing → multi-field validation
        # error; the field map is in ``details``.
        assert response.data["code"] == "validation_error"
        assert "admin_email" in response.data["details"]

    def test_create_rejects_invalid_schema_name_format(
        self, factory, tenant, super_admin
    ):
        """schema_name must be lowercase alphanumeric + underscores."""
        request = factory.post(
            "/tenants/",
            {
                "schema_name": "Has-Dashes",
                "name": "X",
                "domain": "x.example.com",
                "admin_email": "a@b.c",
                "admin_password": "pw",
            },
            format="json",
        )
        force_authenticate(
            request, user=super_admin, token=make_step_up_token(super_admin)
        )
        response = _dispatch({"post": "create"}, request)

        assert response.status_code == 400
        assert "lowercase" in response.data["message"]

    def test_requires_step_up_without_claim(self, factory, tenant, super_admin):
        """Provisioning a tenant mints its first admin — without a fresh step-up
        claim the request is refused before any Tenant row is created."""
        request = factory.post(
            "/tenants/",
            {
                "schema_name": "stepup_newtenant",
                "name": "X",
                "domain": "stepup-new.example.com",
                "admin_email": "a@b.c",
                "admin_password": _STRONG_PW,
            },
            format="json",
        )
        force_authenticate(request, user=super_admin)  # no step-up token
        response = _dispatch({"post": "create"}, request)

        assert response.status_code == 403
        assert response.data["code"] == "auth.step_up_required"
        with schema_context("public"):
            from apps.shared.tenants.models import Tenant

            assert not Tenant.objects.filter(schema_name="stepup_newtenant").exists()

    def test_duplicate_maps_integrity_error_to_400(
        self, factory, tenant, super_admin, monkeypatch
    ):
        """TEN-9: a unique-constraint IntegrityError that slips past the
        pre-check (TOCTOU) is mapped to the precise 400, not a generic 500."""
        from apps.shared.tenants.services import TenantService

        def _raise_domain_dup(self, **kwargs):
            raise IntegrityError(
                "duplicate key value violates unique constraint "
                '"shared_tenants_domain_domain_key"'
            )

        monkeypatch.setattr(TenantService, "provision_tenant", _raise_domain_dup)
        request = factory.post(
            "/tenants/",
            {
                "schema_name": "race_tenant",
                "name": "X",
                "domain": "race.example.com",
                "admin_email": "admin@race.example.com",
                "admin_password": _STRONG_PW,
            },
            format="json",
        )
        force_authenticate(
            request, user=super_admin, token=make_step_up_token(super_admin)
        )
        response = _dispatch({"post": "create"}, request)

        assert response.status_code == 400
        assert response.data["code"] == "super_admin.domain_in_use"


@pytest.mark.django_db
def test_tenant_schema_or_409_translates_missing_schema():
    """TEN-10: a missing/dropped tenant schema (Programming/OperationalError
    inside the block) surfaces as a clean 409 TenantSchemaMissing, not a 500.
    A genuine DoesNotExist would still propagate (→ 404)."""
    from apps.shared.super_admin.errors import TenantSchemaMissing
    from apps.shared.super_admin.viewsets import _tenant_schema_or_409

    class _Tenant:
        schema_name = "ghost_schema_never_created"

    with pytest.raises(TenantSchemaMissing):
        with _tenant_schema_or_409(_Tenant()):
            raise ProgrammingError('relation "accounts_jasminuser" does not exist')


# ---------------------------------------------------------------------------
# Nested resources: users / create-admin / create-user / update-roles
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestUsersAction:
    def test_users_split_admin_vs_other(self, factory, tenant, super_admin):
        admin_user = JasminUserFactory(roles=["admin"])
        office_user = JasminUserFactory(roles=["office"])

        request = factory.get(f"/tenants/{tenant.id}/users/")
        force_authenticate(request, user=super_admin)
        response = _dispatch({"get": "users"}, request, pk=tenant.id)

        assert response.status_code == 200
        admin_ids = {u["id"] for u in response.data["admin_users"]}
        other_ids = {u["id"] for u in response.data["other_users"]}
        assert admin_user.id in admin_ids
        assert office_user.id in other_ids
        assert admin_user.id not in other_ids


@pytest.mark.django_db
class TestCreateAdmin:
    def test_happy_path_creates_admin_user(self, factory, tenant, super_admin):
        request = factory.post(
            f"/tenants/{tenant.id}/create-admin/",
            {
                "first_name": "New",
                "last_name": "Admin",
                "email": "new-admin@example.com",
                "password": _STRONG_PW,
            },
            format="json",
        )
        # create_admin is step-up gated (mints a tenant admin); give the
        # super-admin a fresh step-up claim so the request reaches the body.
        force_authenticate(
            request, user=super_admin, token=make_step_up_token(super_admin)
        )
        response = _dispatch({"post": "create_admin"}, request, pk=tenant.id)

        assert response.status_code == 201
        with schema_context(tenant.schema_name):
            created = JasminUser.objects.get(email="new-admin@example.com")
            assert "admin" in created.roles
            assert created.is_active

    def test_missing_fields_returns_400(self, factory, tenant, super_admin):
        request = factory.post(
            f"/tenants/{tenant.id}/create-admin/",
            {"email": "incomplete@example.com"},
            format="json",
        )
        force_authenticate(
            request, user=super_admin, token=make_step_up_token(super_admin)
        )
        response = _dispatch({"post": "create_admin"}, request, pk=tenant.id)

        assert response.status_code == 400
        # Canonical DRF validation body. (Don't assert on ``message`` — DRF's
        # field messages are locale-translated; LANGUAGE_CODE is "de".)
        assert response.data["code"] == "validation_error"
        assert "first_name" in response.data["details"]

    def test_duplicate_email_returns_400(self, factory, tenant, super_admin):
        JasminUserFactory(email="dup@example.com")
        request = factory.post(
            f"/tenants/{tenant.id}/create-admin/",
            {
                "first_name": "Dup",
                "last_name": "Admin",
                "email": "dup@example.com",
                "password": _STRONG_PW,
            },
            format="json",
        )
        force_authenticate(
            request, user=super_admin, token=make_step_up_token(super_admin)
        )
        response = _dispatch({"post": "create_admin"}, request, pk=tenant.id)

        assert response.status_code == 400
        assert "already exists" in response.data["message"]

    def test_requires_step_up_without_claim(self, factory, tenant, super_admin):
        """Minting a tenant admin is a persistent-backdoor risk — without a
        fresh step-up claim the request is refused before any user is created."""
        request = factory.post(
            f"/tenants/{tenant.id}/create-admin/",
            {
                "first_name": "Step",
                "last_name": "Up",
                "email": "needs-step-up@example.com",
                "password": _STRONG_PW,
            },
            format="json",
        )
        force_authenticate(request, user=super_admin)  # no step-up token
        response = _dispatch({"post": "create_admin"}, request, pk=tenant.id)

        assert response.status_code == 403
        assert response.data["code"] == "auth.step_up_required"
        with schema_context(tenant.schema_name):
            assert not JasminUser.objects.filter(
                email="needs-step-up@example.com"
            ).exists()


@pytest.mark.django_db
class TestCreateUser:
    def test_rejects_reseller_id_without_customer_role(
        self, factory, tenant, super_admin
    ):
        request = factory.post(
            f"/tenants/{tenant.id}/create-user/",
            {
                "first_name": "X",
                "last_name": "Y",
                "email": "no-customer@example.com",
                "password": _STRONG_PW,
                "roles": ["office"],
                "reseller_id": "some-id",
            },
            format="json",
        )
        # create_user is step-up gated (can mint an admin-role account); give
        # the super-admin a fresh step-up claim so the request reaches the body.
        force_authenticate(
            request, user=super_admin, token=make_step_up_token(super_admin)
        )
        response = _dispatch({"post": "create_user"}, request, pk=tenant.id)

        assert response.status_code == 400
        assert "reseller_id" in response.data["message"]

    def test_rejects_invalid_role_combination(self, factory, tenant, super_admin):
        """``customer`` may only combine with ``member`` — adding ``office``
        is rejected at the role-combination check before any DB writes."""
        request = factory.post(
            f"/tenants/{tenant.id}/create-user/",
            {
                "first_name": "X",
                "last_name": "Y",
                "email": "bad-combo@example.com",
                "password": _STRONG_PW,
                "roles": ["customer", "office"],
            },
            format="json",
        )
        force_authenticate(
            request, user=super_admin, token=make_step_up_token(super_admin)
        )
        response = _dispatch({"post": "create_user"}, request, pk=tenant.id)

        assert response.status_code == 400
        assert "customer" in response.data["message"].lower()

    def test_requires_step_up_without_claim(self, factory, tenant, super_admin):
        """Creating a user (roles can include ``admin``) is gated: without a
        fresh step-up claim the request is refused before any user is created."""
        request = factory.post(
            f"/tenants/{tenant.id}/create-user/",
            {
                "first_name": "Step",
                "last_name": "Up",
                "email": "user-needs-step-up@example.com",
                "password": _STRONG_PW,
                "roles": ["office"],
            },
            format="json",
        )
        force_authenticate(request, user=super_admin)  # no step-up token
        response = _dispatch({"post": "create_user"}, request, pk=tenant.id)

        assert response.status_code == 403
        assert response.data["code"] == "auth.step_up_required"
        with schema_context(tenant.schema_name):
            assert not JasminUser.objects.filter(
                email="user-needs-step-up@example.com"
            ).exists()


@pytest.mark.django_db
class TestUpdateUserRoles:
    def test_happy_path_updates_roles(self, factory, tenant, super_admin):
        target = JasminUserFactory(roles=["office"])

        request = factory.patch(
            f"/tenants/{tenant.id}/users/{target.id}/roles/",
            {"roles": ["admin", "office"]},
            format="json",
        )
        # update_user_roles is step-up gated; give the super-admin a fresh
        # step-up claim so the request reaches the action body.
        force_authenticate(
            request, user=super_admin, token=make_step_up_token(super_admin)
        )
        response = _dispatch(
            {"patch": "update_user_roles"},
            request,
            pk=tenant.id,
            user_id=target.id,
        )

        assert response.status_code == 200
        target.refresh_from_db()
        assert set(target.roles) == {"admin", "office"}

    def test_roles_must_be_list(self, factory, tenant, super_admin):
        target = JasminUserFactory(roles=["office"])
        request = factory.patch(
            f"/tenants/{tenant.id}/users/{target.id}/roles/",
            {"roles": "admin"},
            format="json",
        )
        # update_user_roles is step-up gated; give the super-admin a fresh
        # step-up claim so the request reaches the action body.
        force_authenticate(
            request, user=super_admin, token=make_step_up_token(super_admin)
        )
        response = _dispatch(
            {"patch": "update_user_roles"},
            request,
            pk=tenant.id,
            user_id=target.id,
        )

        assert response.status_code == 400
        # ListField ``not_a_list`` → canonical validation_error. (Don't assert
        # on ``message`` — DRF's messages are locale-translated to German.)
        assert response.data["code"] == "validation_error"
        assert "roles" in response.data["details"]

    def test_unknown_user_returns_404(self, factory, tenant, super_admin):
        request = factory.patch(
            f"/tenants/{tenant.id}/users/nonexistent/roles/",
            {"roles": ["office"]},
            format="json",
        )
        # update_user_roles is step-up gated; give the super-admin a fresh
        # step-up claim so the request reaches the action body.
        force_authenticate(
            request, user=super_admin, token=make_step_up_token(super_admin)
        )
        response = _dispatch(
            {"patch": "update_user_roles"},
            request,
            pk=tenant.id,
            user_id="nonexistent",
        )

        assert response.status_code == 404

    def test_rejects_unknown_role(self, factory, tenant, super_admin):
        """TEN-3: a typo'd role is a 400 (InvalidRoles), never silently dropped
        into a different effective role set — roles stay unchanged."""
        target = JasminUserFactory(roles=["office"])
        request = factory.patch(
            f"/tenants/{tenant.id}/users/{target.id}/roles/",
            {"roles": ["admin", "offce"]},  # typo
            format="json",
        )
        force_authenticate(
            request, user=super_admin, token=make_step_up_token(super_admin)
        )
        response = _dispatch(
            {"patch": "update_user_roles"}, request, pk=tenant.id, user_id=target.id
        )

        assert response.status_code == 400
        assert response.data["code"] == "super_admin.invalid_roles"
        target.refresh_from_db()
        assert set(target.roles) == {"office"}

    def test_last_admin_demotion_refused(self, factory, tenant, super_admin):
        """TEN-4: demoting the tenant's only active admin is refused."""
        admin = JasminUserFactory(roles=["admin"])
        request = factory.patch(
            f"/tenants/{tenant.id}/users/{admin.id}/roles/",
            {"roles": ["office"]},
            format="json",
        )
        force_authenticate(
            request, user=super_admin, token=make_step_up_token(super_admin)
        )
        response = _dispatch(
            {"patch": "update_user_roles"}, request, pk=tenant.id, user_id=admin.id
        )

        assert response.status_code == 400
        assert response.data["code"] == "super_admin.last_admin"
        admin.refresh_from_db()
        assert "admin" in admin.roles

    def test_last_admin_demotion_allowed_with_force(self, factory, tenant, super_admin):
        """TEN-4: force=true is the explicit recovery escape hatch."""
        admin = JasminUserFactory(roles=["admin"])
        request = factory.patch(
            f"/tenants/{tenant.id}/users/{admin.id}/roles/",
            {"roles": ["office"], "force": True},
            format="json",
        )
        force_authenticate(
            request, user=super_admin, token=make_step_up_token(super_admin)
        )
        response = _dispatch(
            {"patch": "update_user_roles"}, request, pk=tenant.id, user_id=admin.id
        )

        assert response.status_code == 200
        admin.refresh_from_db()
        assert "admin" not in admin.roles

    def test_demote_admin_allowed_when_another_admin_exists(
        self, factory, tenant, super_admin
    ):
        """TEN-4: with another active admin present, demotion is allowed."""
        JasminUserFactory(roles=["admin"])  # another active admin
        admin = JasminUserFactory(roles=["admin"])
        request = factory.patch(
            f"/tenants/{tenant.id}/users/{admin.id}/roles/",
            {"roles": ["office"]},
            format="json",
        )
        force_authenticate(
            request, user=super_admin, token=make_step_up_token(super_admin)
        )
        response = _dispatch(
            {"patch": "update_user_roles"}, request, pk=tenant.id, user_id=admin.id
        )

        assert response.status_code == 200
        admin.refresh_from_db()
        assert "admin" not in admin.roles
