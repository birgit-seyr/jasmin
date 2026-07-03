from __future__ import annotations

from rest_framework import serializers

from apps.shared.tenants.provisioning import (
    normalize_domain as _normalize_domain,
)
from apps.shared.tenants.provisioning import (
    validate_admin_password as _validate_admin_password,
)
from apps.shared.tenants.provisioning import (
    validate_schema_name as _validate_schema_name,
)

# --- List Tenants ---


class TenantListItemSerializer(serializers.Serializer):
    # Tenant.id is a 12-char nanoid STRING (JasminModel pk) — never
    # IntegerField. Same for the detail/update serializers below.
    id = serializers.CharField()
    schema_name = serializers.CharField()
    name = serializers.CharField()
    domain = serializers.CharField(allow_null=True)
    created_on = serializers.DateTimeField()
    is_active = serializers.BooleanField()
    # Null when the list was fetched with ``include_user_count=false``.
    user_count = serializers.IntegerField(allow_null=True)


# --- Create Tenant ---


class CreateTenantRequestSerializer(serializers.Serializer):
    schema_name = serializers.CharField()
    name = serializers.CharField()
    domain = serializers.CharField()
    tenant_language = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    admin_email = serializers.EmailField()
    admin_password = serializers.CharField()
    admin_first_name = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    admin_last_name = serializers.CharField(
        required=False, allow_blank=True, default=""
    )

    # Delegate to the shared tenants helper so the HTTP path, the create_tenant
    # CLI, and provision_tenant all enforce the SAME allowlist (no drift).
    def validate_schema_name(self, value: str) -> str:
        return _validate_schema_name(value)

    def validate_domain(self, value: str) -> str:
        return _normalize_domain(value)

    def validate_admin_password(self, value: str) -> str:
        return _validate_admin_password(value)


class CreateTenantResponseSerializer(serializers.Serializer):
    id = serializers.CharField()
    schema_name = serializers.CharField()
    name = serializers.CharField()
    domain = serializers.CharField()
    created_on = serializers.DateTimeField()
    admin_email = serializers.CharField()
    message = serializers.CharField()


# --- Tenant Detail ---


class DomainSerializer(serializers.Serializer):
    domain = serializers.CharField()
    is_primary = serializers.BooleanField()


class TenantDetailResponseSerializer(serializers.Serializer):
    id = serializers.CharField()
    schema_name = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    tenant_language = serializers.CharField()
    domains = DomainSerializer(many=True)
    created_on = serializers.DateTimeField()
    is_active = serializers.BooleanField()


# --- Tenant Users ---


class TenantUserSerializer(serializers.Serializer):
    """One JasminUser row inside a tenant schema, as listed by the
    ``users`` action on ``TenantManagementViewSet``."""

    # JasminUser.id is a 12-char nanoid STRING (JasminModel pk).
    id = serializers.CharField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    email = serializers.EmailField()
    roles = serializers.ListField(child=serializers.CharField())
    is_active = serializers.BooleanField()
    account_status = serializers.CharField()
    date_joined = serializers.DateTimeField()
    last_login = serializers.DateTimeField(allow_null=True)


class TenantUserListResponseSerializer(serializers.Serializer):
    admin_users = TenantUserSerializer(many=True)
    other_users = TenantUserSerializer(many=True)


# --- Tenant Resellers ---


class ResellerListItemSerializer(serializers.Serializer):
    """One active reseller row, as listed by the ``resellers`` action
    on ``TenantManagementViewSet``."""

    id = serializers.CharField()
    customer_number = serializers.IntegerField(allow_null=True)
    filial_number = serializers.IntegerField(allow_null=True)
    name_for_member_pages = serializers.CharField(allow_blank=True, allow_null=True)
    linked_user_id = serializers.CharField(allow_null=True)
    display = serializers.CharField()


# --- Super Admin Session (login response) ---


class SessionUserSerializer(serializers.Serializer):
    """Identity block in the super-admin login response.

    ``SuperAdmin`` lives on the public schema and uses Django's
    default integer pk — NOT the JasminModel nanoid string.
    """

    id = serializers.IntegerField()
    email = serializers.EmailField()
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    is_superuser = serializers.BooleanField()
    is_staff = serializers.BooleanField()
    permissions = serializers.ListField(child=serializers.CharField())


class SessionTenantSerializer(serializers.Serializer):
    """One tenant entry in the super-admin login response."""

    id = serializers.CharField()
    name = serializers.CharField()
    schema_name = serializers.CharField()
    domain = serializers.CharField(allow_null=True)


# --- Update Tenant ---


class UpdateTenantRequestSerializer(serializers.Serializer):
    name = serializers.CharField(required=False)
    description = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )
    is_active = serializers.BooleanField(required=False)


class UpdateTenantResponseSerializer(serializers.Serializer):
    id = serializers.CharField()
    schema_name = serializers.CharField()
    name = serializers.CharField()
    message = serializers.CharField()


# --- Create Tenant Admin ---


class CreateTenantAdminRequestSerializer(serializers.Serializer):
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    email = serializers.EmailField()
    # trim_whitespace=False: a password is taken verbatim (matches the
    # CreateTenantUser serializer).
    password = serializers.CharField(trim_whitespace=False)

    def validate_password(self, value: str) -> str:
        return _validate_admin_password(value)


class CreateTenantAdminResponseSerializer(serializers.Serializer):
    id = serializers.CharField()
    email = serializers.CharField()
    message = serializers.CharField()


# --- Create Tenant User ---


class CreateTenantUserRequestSerializer(serializers.Serializer):
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    email = serializers.EmailField()
    # trim_whitespace=False: a password is taken verbatim — DRF's default would
    # silently strip surrounding spaces the user typed.
    password = serializers.CharField(trim_whitespace=False)
    roles = serializers.ListField(child=serializers.CharField(), required=False)
    reseller_id = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )

    def validate_password(self, value: str) -> str:
        return _validate_admin_password(value)


class CreateTenantUserResponseSerializer(serializers.Serializer):
    id = serializers.CharField()
    email = serializers.CharField()
    roles = serializers.ListField(child=serializers.CharField())
    reseller_id = serializers.CharField(required=False, allow_null=True)
    message = serializers.CharField()


# --- Update User Roles ---


class UpdateUserRolesRequestSerializer(serializers.Serializer):
    roles = serializers.ListField(child=serializers.CharField())
    # Escape hatch: demoting a tenant's LAST active admin is refused unless
    # force=True (legitimate super-admin recovery may need to bypass).
    force = serializers.BooleanField(required=False, default=False)


class UpdateUserRolesResponseSerializer(serializers.Serializer):
    id = serializers.CharField()
    roles = serializers.ListField(child=serializers.CharField())
    message = serializers.CharField()


# --- Backups ---


class BackupFileSerializer(serializers.Serializer):
    """One encrypted backup file on disk, as listed by the
    backup-list endpoint."""

    filename = serializers.CharField()
    size_bytes = serializers.IntegerField()
    size_human = serializers.CharField()
    created_at = serializers.DateTimeField()


# --- Ops Checklist ------------------------------------------------------------


class OpsChecklistRunSerializer(serializers.Serializer):
    """One completion entry from the append-only run log."""

    id = serializers.IntegerField()
    completed_at = serializers.DateTimeField()
    completed_by_email = serializers.CharField(allow_null=True)
    notes = serializers.CharField(allow_blank=True)


class OpsChecklistItemSerializer(serializers.Serializer):
    """A single checklist item with its computed schedule + last run."""

    id = serializers.IntegerField()
    kind = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    interval_days = serializers.IntegerField()
    is_active = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    last_run = OpsChecklistRunSerializer(allow_null=True)
    next_due_at = serializers.DateTimeField()
    is_overdue = serializers.BooleanField()


class OpsChecklistMarkDoneRequestSerializer(serializers.Serializer):
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="What changed, what was rotated, what worked.",
    )


class RunRotationResponseSerializer(serializers.Serializer):
    """Mirror of ``services.rotation.RotationResult``."""

    kind = serializers.CharField()
    # Populated only when the rotation generates a value the operator
    # must copy somewhere (.env, Postgres role). Returned exactly
    # once, never logged.
    generated_secret = serializers.CharField(allow_null=True)
    instructions = serializers.CharField()
    items_affected = serializers.IntegerField()
    extras = serializers.DictField(child=serializers.CharField())
