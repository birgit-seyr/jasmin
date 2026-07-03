"""Shared validation for tenant provisioning inputs.

The schema-name denylist, domain normalization, and admin-password policy must
hold for EVERY caller of ``TenantService.provision_tenant`` (the super-admin
HTTP serializer, the dev seeder) — not just the HTTP path. Enforcing them at the
sink is what stops any caller from provisioning a Tenant row onto a reserved or
pre-existing Postgres schema — and the self-cleaning failure path from then
``DROP SCHEMA CASCADE``-ing a schema this call never created.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError

from .errors import (
    InvalidDomain,
    InvalidSchemaName,
    ReservedDomain,
    WeakPassword,
)

# The shared/platform schema and the Postgres system schema. ``pg_*`` is
# checked separately (django-tenants also blocks it, but we don't rely on that).
_RESERVED_SCHEMA_NAMES = {"public", "information_schema"}


def validate_schema_name(value: str) -> str:
    """Return a Postgres-safe, non-reserved schema name or raise.

    Lowercase alphanumeric + underscores only; never the public/platform schema
    nor a ``pg_*`` / ``information_schema`` namespace.
    """
    value = (value or "").strip()
    if not value or not value.replace("_", "").isalnum() or value != value.lower():
        raise InvalidSchemaName(
            "schema_name must be lowercase alphanumeric with underscores only"
        )
    public_name = getattr(settings, "PUBLIC_SCHEMA_NAME", "public").lower()
    if (
        value in _RESERVED_SCHEMA_NAMES
        or value == public_name
        or value.startswith("pg_")
    ):
        raise InvalidSchemaName(
            "schema_name must not be a reserved or platform schema name"
        )
    return value


def normalize_domain(value: str) -> str:
    """Lowercase + strip the domain and reject the platform subdomain.

    The request ``Host`` is matched case-sensitively, so an uppercased domain
    would persist but be silently unreachable; and a tenant must not claim the
    platform's first label (it would shadow super-admin routing).
    """
    value = (value or "").strip().lower()
    if not value:
        raise InvalidDomain("domain must not be blank")
    platform_label = getattr(settings, "SUPER_ADMIN_SUBDOMAIN", "marillen").lower()
    if value.split(".", 1)[0] == platform_label:
        raise ReservedDomain("domain is reserved for the platform")
    return value


def validate_admin_password(value: str) -> str:
    """Enforce ``AUTH_PASSWORD_VALIDATORS`` on a privileged account's password.

    No user instance at create time (matches the registration flow), so
    similarity checks are skipped — length / common / numeric / zxcvbn still
    apply. Re-raises Django's ``ValidationError`` as the canonical
    ``WeakPassword`` Jasmin error.
    """
    try:
        password_validation.validate_password(value)
    except DjangoValidationError as exc:
        raise WeakPassword("; ".join(exc.messages)) from exc
    return value
