"""Super-admin (platform) domain errors.

All subclasses of :class:`core.errors.JasminError`, so the global
exception handler renders them as the canonical
``{code, message, field?, details?}`` body with the right HTTP status —
views raise, they don't build ``Response`` objects by hand.
"""

from __future__ import annotations

from core.errors import (
    AuthError,
    BadRequestError,
    ConflictError,
    ForbiddenError,
    JasminError,
    NotFoundError,
)

# --------------------------------------------------------------------------- #
# Tenant management                                                            #
# --------------------------------------------------------------------------- #


class TenantNotFound(NotFoundError):
    code = "super_admin.tenant_not_found"


class TenantUserNotFound(NotFoundError):
    code = "super_admin.user_not_found"


class TenantSchemaMissing(ConflictError):
    """The Tenant row exists but its Postgres schema is gone (a partially-
    cleaned orphan, or a manual DROP). An inconsistent platform state — surfaced
    as 409 rather than a confusing unhandled 500."""

    code = "super_admin.tenant_schema_missing"


class DomainInUse(BadRequestError):
    code = "super_admin.domain_in_use"


class TenantProvisioningFailed(JasminError):
    """Multi-step tenant provisioning failed.

    The client gets a generic message only — the underlying exception is
    logged server-side, never leaked into the response body.
    """

    code = "super_admin.tenant_provisioning_failed"
    http_status = 500


class UserEmailExists(BadRequestError):
    code = "super_admin.user_email_exists"


class InvalidRoles(BadRequestError):
    """Roles payload is malformed, contains unknown roles, or is an
    invalid combination."""

    code = "super_admin.invalid_roles"


class LastAdminProtected(BadRequestError):
    """Refused: the change would strip 'admin' from a tenant's last active
    admin, leaving it administrator-less. Pass ``force=true`` to override
    (legitimate super-admin recovery)."""

    code = "super_admin.last_admin"


class ResellerNotFound(BadRequestError):
    """Declared as 400 (not 404): the reseller id is part of the request
    payload, so a bad id is input validation on this endpoint."""

    code = "super_admin.reseller_not_found"


class ResellerAlreadyLinked(BadRequestError):
    code = "super_admin.reseller_already_linked"


# --------------------------------------------------------------------------- #
# Auth flow                                                                    #
# --------------------------------------------------------------------------- #


class SuperAdminMissingCredentials(BadRequestError):
    """Login payload is missing email or password — input validation."""

    code = "super_admin.missing_credentials"


class SuperAdminInvalidCredentials(BadRequestError):
    """Wrong email/password.

    Deliberately 400 (not the HTTP-standard 401), mirroring the tenant-side
    ``apps.accounts.errors.InvalidCredentials``: the frontend treats 401 as
    "session expired, try silent refresh" and a 401 here would trigger the
    refresh interceptor instead of showing the real failure.
    """

    code = "super_admin.invalid_credentials"


class SuperAdminAccountDisabled(ForbiddenError):
    code = "super_admin.account_disabled"


class SuperAdminAccountLocked(JasminError):
    """Too many failed login attempts on this super-admin account — refused for
    a cooldown window (per-account brute-force lockout; see
    ``super_admin/lockout.py``). 429 so the client backs off, distinct from the
    400 invalid-credentials response."""

    code = "super_admin.account_locked"
    http_status = 429


class RefreshTokenMissing(AuthError):
    code = "super_admin.refresh_token_missing"


class RefreshTokenInvalid(AuthError):
    code = "super_admin.refresh_token_invalid"


class NotSuperAdminToken(AuthError):
    code = "super_admin.not_super_admin_token"


# --------------------------------------------------------------------------- #
# Backups                                                                      #
# --------------------------------------------------------------------------- #


class BackupScriptMissing(JasminError):
    code = "super_admin.backup_script_missing"
    http_status = 500


class BackupFailed(JasminError):
    code = "super_admin.backup_failed"
    http_status = 500


class BackupTimedOut(JasminError):
    code = "super_admin.backup_timed_out"
    http_status = 504
