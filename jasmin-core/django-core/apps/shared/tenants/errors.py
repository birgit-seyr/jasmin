"""Tenant-app domain errors.

All subclasses of :class:`core.errors.JasminError`, so the global
exception handler renders them as the canonical
``{code, message, field?, details?}`` body with the right HTTP status —
views raise, they don't build ``Response`` objects by hand.
"""

from __future__ import annotations

from core.errors import BadRequestError

# --------------------------------------------------------------------------- #
# Provisioning input validation                                               #
# These guards must hold for EVERY caller of provision_tenant (HTTP serializer, #
# the dev seeder), so they live in the shared tenants layer rather than only in #
# the super-admin serializer.                                                   #
# --------------------------------------------------------------------------- #


class InvalidSchemaName(BadRequestError):
    """schema_name is malformed, or targets a reserved/platform schema
    (``public``, ``information_schema``, ``pg_*``, the configured
    ``PUBLIC_SCHEMA_NAME``)."""

    code = "tenant.invalid_schema_name"


class SchemaAlreadyExists(BadRequestError):
    """A Postgres schema with this name already exists (with or without an
    owning Tenant row). Refused up front so provisioning never migrates into —
    nor, on a later failure, ``DROP SCHEMA CASCADE``s — a schema this call did
    not create."""

    code = "tenant.schema_already_exists"


class InvalidDomain(BadRequestError):
    code = "tenant.invalid_domain"


class ReservedDomain(BadRequestError):
    """The domain's first label is the platform/super-admin subdomain, which
    would shadow platform routing."""

    code = "tenant.reserved_domain"


class WeakPassword(BadRequestError):
    """The admin password fails ``AUTH_PASSWORD_VALIDATORS``. Privileged
    (admin-capable) accounts must meet the same policy as member registration
    and password reset."""

    code = "tenant.weak_password"


class NoTenantContext(BadRequestError):
    """Request arrived without a tenant context (public schema or no
    ``request.tenant``) — tenant-scoped endpoints cannot serve it."""

    code = "tenant.no_context"


class YearNumberingLocked(BadRequestError):
    """A year-based numbering setting cannot be changed anymore because
    documents of the corresponding type already exist."""

    code = "tenant_settings.year_numbering_locked"


class EmptyNumberingPrefix(BadRequestError):
    """A document-numbering prefix was blanked. These are legal-document
    labels (``RE-`` on invoices, the correction prefix on stornos) — a blank
    prefix yields unlabeled, ambiguous number sequences (e.g. stornos
    rendering as bare 1, 2, 3 while invoices keep ``RE-``), so empty is
    refused. ``update_current_settings`` bypasses the serializer's
    ``allow_blank=False``, so this is enforced explicitly there."""

    code = "tenant_settings.empty_numbering_prefix"


class CoopSharesBoundsInverted(BadRequestError):
    """The configured coop-share window is inverted (min > max). No member
    total can satisfy it, so every non-trial coop-share save and admin
    confirmation would be blocked for the tenant — refuse the save."""

    code = "tenant_settings.coop_shares_bounds_inverted"


class InvalidSettingsValue(BadRequestError):
    """A settings value fails the model field validators (e.g.
    ``billing_due_day_of_month`` / ``sepa_collection_day_of_month`` outside
    1-28, ``season_start_week`` outside 1-53). ``update_current_settings``
    setattr's raw values and is the ONLY write path, so it must run
    ``full_clean`` explicitly — an out-of-range day would otherwise persist and
    later crash charge-schedule generation."""

    code = "tenant_settings.invalid_value"


class TestEmailRecipientMissing(BadRequestError):
    code = "email_config.test_recipient_missing"


class EmailConfigNotSetUp(BadRequestError):
    code = "email_config.not_set_up"


class TestEmailRecipientNotAllowed(BadRequestError):
    """Test sends are restricted to the requesting user's own email and
    the (admin-controlled) tenant contact email — a compromised office
    account must not be able to use the tenant's SMTP as a spam relay.
    The office-writable sender / reply-to addresses are deliberately
    not allowed."""

    code = "email_config.test_recipient_not_allowed"


class TestEmailSendFailed(BadRequestError):
    code = "email_config.test_send_failed"
