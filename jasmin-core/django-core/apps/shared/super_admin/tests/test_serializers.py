"""Contract tests for super-admin serializers.

These are pure declarative ``Serializer`` subclasses — no ``validate()``,
no ``create()`` / ``update()``. There's no business logic to exercise.
What we want to lock down is the **wire contract**: field names + which
are required vs optional. The frontend ``apps/shared/super_admin/`` API
client is generated from this schema (via ``drf-spectacular``); a silent
rename of, say, ``admin_email`` → ``adminEmail`` would break login at
the next ``npm run generate-api`` without anything else noticing.

For each request serializer we cover:
- a happy-path payload validates and exposes the expected
  ``validated_data`` shape;
- omitting a required field fails with that field surfaced in
  ``serializer.errors``;
- optional fields can be omitted without error.

Response serializers are tested by instantiation + ``.data`` round-trip
on a documented payload — proves the declared types accept the shapes
the viewsets actually return.
"""

from __future__ import annotations

import datetime

import pytest
from django.conf import settings

from apps.shared.super_admin.serializers import (
    CreateTenantAdminRequestSerializer,
    CreateTenantAdminResponseSerializer,
    CreateTenantRequestSerializer,
    CreateTenantResponseSerializer,
    CreateTenantUserRequestSerializer,
    CreateTenantUserResponseSerializer,
    OpsChecklistItemSerializer,
    OpsChecklistMarkDoneRequestSerializer,
    OpsChecklistRunSerializer,
    TenantDetailResponseSerializer,
    TenantListItemSerializer,
    TenantUserListResponseSerializer,
    UpdateTenantRequestSerializer,
    UpdateTenantResponseSerializer,
    UpdateUserRolesRequestSerializer,
    UpdateUserRolesResponseSerializer,
)

# A password that satisfies AUTH_PASSWORD_VALIDATORS (12-char min + zxcvbn +
# common/numeric). TEN-5 enforces that policy on these privileged serializers,
# so happy-path fixtures must use a strong value.
_STRONG_PW = "9xKqP2mwLvZt7Rdn"

# ---------------------------------------------------------------------------
# Request serializers — validate happy / missing / extra-optional paths
# ---------------------------------------------------------------------------


class TestCreateTenantRequest:
    HAPPY = {
        "schema_name": "newtenant",
        "name": "New Farm",
        "domain": "new.example.com",
        "admin_email": "admin@example.com",
        "admin_password": _STRONG_PW,
    }

    def test_happy_path_validates(self):
        ser = CreateTenantRequestSerializer(data=self.HAPPY)
        assert ser.is_valid(), ser.errors
        assert ser.validated_data["schema_name"] == "newtenant"
        assert ser.validated_data["admin_email"] == "admin@example.com"

    @pytest.mark.parametrize(
        "missing_field",
        ["schema_name", "name", "domain", "admin_email", "admin_password"],
    )
    def test_missing_required_field_fails(self, missing_field):
        payload = {k: v for k, v in self.HAPPY.items() if k != missing_field}
        ser = CreateTenantRequestSerializer(data=payload)
        assert not ser.is_valid()
        assert missing_field in ser.errors

    def test_optional_fields_can_be_omitted(self):
        ser = CreateTenantRequestSerializer(data=self.HAPPY)
        assert ser.is_valid()
        # tenant_language / admin_first_name / admin_last_name are NOT in
        # HAPPY and must not block validation.
        for optional in (
            "tenant_language",
            "admin_first_name",
            "admin_last_name",
        ):
            assert optional not in ser.errors

    def test_invalid_email_rejected(self):
        ser = CreateTenantRequestSerializer(
            data={**self.HAPPY, "admin_email": "not-an-email"}
        )
        assert not ser.is_valid()
        assert "admin_email" in ser.errors

    @pytest.mark.parametrize(
        "bad_schema", ["public", "pg_catalog", "information_schema"]
    )
    def test_reserved_schema_name_rejected(self, bad_schema):
        # TEN-6: the validator rejects platform/reserved schemas itself, not
        # relying on a 'public' Tenant sentinel row existing. Field validators
        # raise a JasminError (rendered by the global handler), so is_valid()
        # propagates it rather than collecting a DRF field error.
        from apps.shared.tenants.errors import InvalidSchemaName

        ser = CreateTenantRequestSerializer(
            data={**self.HAPPY, "schema_name": bad_schema}
        )
        with pytest.raises(InvalidSchemaName):
            ser.is_valid()

    def test_domain_is_lowercased(self):
        # TEN-7: routing matches Host case-sensitively, so the domain is
        # normalised to lowercase (else the tenant is silently unreachable).
        ser = CreateTenantRequestSerializer(
            data={**self.HAPPY, "domain": "New.Example.COM"}
        )
        assert ser.is_valid(), ser.errors
        assert ser.validated_data["domain"] == "new.example.com"

    def test_platform_subdomain_rejected(self):
        # TEN-7: a tenant must not claim the platform host's first label.
        from apps.shared.tenants.errors import ReservedDomain

        ser = CreateTenantRequestSerializer(
            data={
                **self.HAPPY,
                "domain": f"{settings.SUPER_ADMIN_SUBDOMAIN}.localhost",
            }
        )
        with pytest.raises(ReservedDomain):
            ser.is_valid()


class TestUpdateTenantRequest:
    def test_all_fields_optional(self):
        """All three fields are optional — an empty PATCH must validate
        (the view accepts no-op updates)."""
        ser = UpdateTenantRequestSerializer(data={})
        assert ser.is_valid(), ser.errors

    def test_each_field_accepts_its_type(self):
        ser = UpdateTenantRequestSerializer(
            data={"name": "Renamed", "description": "new", "is_active": False}
        )
        assert ser.is_valid(), ser.errors
        assert ser.validated_data == {
            "name": "Renamed",
            "description": "new",
            "is_active": False,
        }


class TestCreateTenantAdminRequest:
    HAPPY = {
        "first_name": "Admin",
        "last_name": "Person",
        "email": "admin@x.com",
        "password": _STRONG_PW,
    }

    def test_happy_path(self):
        ser = CreateTenantAdminRequestSerializer(data=self.HAPPY)
        assert ser.is_valid(), ser.errors

    @pytest.mark.parametrize(
        "missing", ["first_name", "last_name", "email", "password"]
    )
    def test_all_fields_required(self, missing):
        payload = {k: v for k, v in self.HAPPY.items() if k != missing}
        ser = CreateTenantAdminRequestSerializer(data=payload)
        assert not ser.is_valid()
        assert missing in ser.errors


class TestCreateTenantUserRequest:
    HAPPY = {
        "first_name": "User",
        "last_name": "Person",
        "email": "user@x.com",
        "password": _STRONG_PW,
    }

    def test_minimal_payload_validates(self):
        """roles + reseller_id are optional — caller can omit both."""
        ser = CreateTenantUserRequestSerializer(data=self.HAPPY)
        assert ser.is_valid(), ser.errors

    def test_roles_accepted_as_string_list(self):
        ser = CreateTenantUserRequestSerializer(
            data={**self.HAPPY, "roles": ["office", "admin"]}
        )
        assert ser.is_valid(), ser.errors
        assert ser.validated_data["roles"] == ["office", "admin"]

    def test_reseller_id_accepts_null_and_blank(self):
        """The frontend may send ``""`` or ``null`` for "no reseller link" —
        both must pass without error (the viewset checks ``or None``)."""
        for value in ("", None):
            ser = CreateTenantUserRequestSerializer(
                data={**self.HAPPY, "reseller_id": value}
            )
            assert ser.is_valid(), (value, ser.errors)


class TestUpdateUserRolesRequest:
    def test_requires_roles_list(self):
        ser = UpdateUserRolesRequestSerializer(data={"roles": ["admin"]})
        assert ser.is_valid(), ser.errors

    def test_roles_field_required(self):
        ser = UpdateUserRolesRequestSerializer(data={})
        assert not ser.is_valid()
        assert "roles" in ser.errors

    def test_non_list_rejected(self):
        ser = UpdateUserRolesRequestSerializer(data={"roles": "admin"})
        assert not ser.is_valid()
        assert "roles" in ser.errors


class TestOpsChecklistMarkDoneRequest:
    def test_empty_payload_uses_default_note(self):
        """``notes`` defaults to ``""`` — POSTing an empty body must
        still validate so the UI can mark items done without a note."""
        ser = OpsChecklistMarkDoneRequestSerializer(data={})
        assert ser.is_valid(), ser.errors
        assert ser.validated_data.get("notes", "") == ""

    def test_with_notes(self):
        ser = OpsChecklistMarkDoneRequestSerializer(data={"notes": "rotated"})
        assert ser.is_valid()
        assert ser.validated_data["notes"] == "rotated"

    def test_blank_notes_allowed(self):
        ser = OpsChecklistMarkDoneRequestSerializer(data={"notes": ""})
        assert ser.is_valid(), ser.errors


# ---------------------------------------------------------------------------
# Response serializers — instantiate + serialize the contract shape
# ---------------------------------------------------------------------------


def _serialize(serializer_cls, instance_data):
    """Helper: serialize the given dict through ``serializer_cls`` and
    return ``.data`` (raises if the shape doesn't match)."""
    return serializer_cls(instance=instance_data).data


class TestResponseSerializerShapes:
    def test_tenant_list_item(self):
        out = _serialize(
            TenantListItemSerializer,
            {
                "id": 1,
                "schema_name": "tenant_a",
                "name": "Farm A",
                "domain": "a.example.com",
                "created_on": datetime.datetime(2026, 1, 1, 12, 0),
                "is_active": True,
                "user_count": 42,
            },
        )
        assert out["schema_name"] == "tenant_a"
        assert out["user_count"] == 42

    def test_tenant_list_item_allows_null_domain(self):
        out = _serialize(
            TenantListItemSerializer,
            {
                "id": 1,
                "schema_name": "no_domain",
                "name": "X",
                "domain": None,
                "created_on": datetime.datetime(2026, 1, 1),
                "is_active": False,
                "user_count": 0,
            },
        )
        assert out["domain"] is None

    def test_create_tenant_response(self):
        out = _serialize(
            CreateTenantResponseSerializer,
            {
                "id": "abc12345",
                "schema_name": "new",
                "name": "New Farm",
                "domain": "new.example.com",
                "created_on": datetime.datetime(2026, 5, 25, 10, 0),
                "admin_email": "a@b.c",
                "message": "ok",
            },
        )
        assert out["id"] == "abc12345"

    def test_tenant_detail_response(self):
        out = _serialize(
            TenantDetailResponseSerializer,
            {
                "id": "abc12345",
                "schema_name": "tenant",
                "name": "X",
                "description": "stuff",
                "tenant_language": "de",
                "domains": [{"domain": "x.com", "is_primary": True}],
                "created_on": datetime.datetime(2026, 1, 1),
                "is_active": True,
            },
        )
        assert out["domains"] == [{"domain": "x.com", "is_primary": True}]
        assert out["tenant_language"] == "de"

    def test_tenant_user_list_response(self):
        # TenantUserSerializer is fully typed now — fixtures carry the
        # complete row shape the viewset's ``users`` action emits.
        user_row = {
            "id": "aB3xK9mPqR2t",
            "first_name": "Anna",
            "last_name": "Apfel",
            "email": "a@b.c",
            "roles": ["admin"],
            "is_active": True,
            "account_status": "active",
            "date_joined": datetime.datetime(2026, 1, 1, 12, 0),
            "last_login": None,
        }
        out = _serialize(
            TenantUserListResponseSerializer,
            {"admin_users": [user_row], "other_users": []},
        )
        assert len(out["admin_users"]) == 1
        assert out["admin_users"][0]["email"] == "a@b.c"
        assert out["admin_users"][0]["last_login"] is None
        assert out["other_users"] == []

    def test_update_tenant_response(self):
        out = _serialize(
            UpdateTenantResponseSerializer,
            {"id": 5, "schema_name": "t", "name": "X", "message": "done"},
        )
        assert out["message"] == "done"

    def test_create_tenant_admin_response(self):
        out = _serialize(
            CreateTenantAdminResponseSerializer,
            {"id": "user1", "email": "a@b.c", "message": "ok"},
        )
        assert out["id"] == "user1"

    def test_create_tenant_user_response(self):
        out = _serialize(
            CreateTenantUserResponseSerializer,
            {
                "id": "user2",
                "email": "u@x.com",
                "roles": ["office"],
                "reseller_id": None,
                "message": "ok",
            },
        )
        assert out["roles"] == ["office"]
        assert out["reseller_id"] is None

    def test_update_user_roles_response(self):
        out = _serialize(
            UpdateUserRolesResponseSerializer,
            {"id": "user2", "roles": ["admin", "office"], "message": "ok"},
        )
        assert out["roles"] == ["admin", "office"]


class TestOpsChecklistResponseSerializers:
    def test_run_serializer_allows_null_completed_by(self):
        """``completed_by_email`` is ``allow_null=True`` because the run
        can be performed by a deleted user (FK on_delete=SET_NULL)."""
        out = _serialize(
            OpsChecklistRunSerializer,
            {
                "id": 1,
                "completed_at": datetime.datetime(2026, 5, 1),
                "completed_by_email": None,
                "notes": "",
            },
        )
        assert out["completed_by_email"] is None

    def test_item_serializer_with_nested_last_run(self):
        out = _serialize(
            OpsChecklistItemSerializer,
            {
                "id": 1,
                "kind": "rotate_django_secret",
                "title": "Rotate DJANGO_SECRET_KEY",
                "description": "do the thing",
                "interval_days": 90,
                "is_active": True,
                "created_at": datetime.datetime(2026, 1, 1),
                "last_run": {
                    "id": 7,
                    "completed_at": datetime.datetime(2026, 4, 1),
                    "completed_by_email": "ops@example.com",
                    "notes": "rotated cleanly",
                },
                "next_due_at": datetime.datetime(2026, 7, 1),
                "is_overdue": False,
            },
        )
        assert out["last_run"]["completed_by_email"] == "ops@example.com"
        assert out["is_overdue"] is False

    def test_item_serializer_with_null_last_run(self):
        """Brand-new item that's never been marked done → ``last_run`` is
        ``None``. The nested serializer must accept that."""
        out = _serialize(
            OpsChecklistItemSerializer,
            {
                "id": 1,
                "kind": "custom",
                "title": "Never run yet",
                "description": "",
                "interval_days": 30,
                "is_active": True,
                "created_at": datetime.datetime(2026, 1, 1),
                "last_run": None,
                "next_due_at": datetime.datetime(2026, 2, 1),
                "is_overdue": False,
            },
        )
        assert out["last_run"] is None
