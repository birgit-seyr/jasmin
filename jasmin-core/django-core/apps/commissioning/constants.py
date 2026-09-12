"""Commissioning-app constants and tenant-aware default helpers.

The ``get_default_tax_rate_*`` helpers resolve the tenant's configured
default tax rate, falling back to a hardcoded constant only when the
tenant context is genuinely unavailable (e.g. during system startup
when no tenant is bound to the connection, or on an unmigrated DB).
"""

import logging

logger = logging.getLogger(__name__)

ID_LENGTH = 12  # this is the ID in the JasminModel

# Use URL-safe alphabet (excludes similar-looking characters, excludes "_", this is needed for composite IDs!)
JASMIN_ID_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"

DEFAULT_TAX_RATE = 7
DEFAULT_CRATE_TAX_RATE = 19

PURCHASE_DAY = 1  # tuesday


def _resolve_tenant_setting(attr_name: str):
    """Return ``TenantSettings.<attr_name>`` for the active tenant, or
    ``None`` if no tenant context is available.

    Previously a bare ``except Exception: pass`` swallowed every error
    here, including transient DB errors and code bugs — which silently
    returned the hardcoded default tax rate for GoBD-relevant
    computations. We now catch only the small set of exceptions that
    legitimately mean "no tenant context to read from":

    * ``ImproperlyConfigured`` — bound connection has no tenant.
    * ``OperationalError`` / ``ProgrammingError`` — DB unreachable or
      ``shared_tenants_tenantsettings`` table doesn't exist yet
      (initial migrations, test setup).
    * ``AttributeError`` — ``connection.tenant`` is missing entirely
      (running outside django-tenants).

    Everything else (model errors, attribute typos in the settings
    field, etc.) bubbles up so the bug gets seen.
    """
    from django.core.exceptions import ImproperlyConfigured
    from django.db import OperationalError, ProgrammingError, connection

    from apps.shared.tenants.models import TenantSettings

    try:
        tenant = connection.tenant
    except AttributeError:
        logger.debug(
            "tax_rate.no_tenant_context attr=%s — falling back to constant",
            attr_name,
        )
        return None

    try:
        settings = TenantSettings.get_current_settings(tenant)
    except (ImproperlyConfigured, OperationalError, ProgrammingError) as exc:
        logger.warning(
            "tax_rate.lookup_failed attr=%s error=%s — falling back to constant",
            attr_name,
            exc,
        )
        return None

    if settings is None:
        return None
    return getattr(settings, attr_name, None)


def get_default_tax_rate_articles():
    """Get the tenant's default tax rate for articles, falling back to hardcoded default."""
    value = _resolve_tenant_setting("default_tax_rate_articles")
    return value if value is not None else DEFAULT_TAX_RATE


def get_default_tax_rate_crates():
    """Get the tenant's default tax rate for crates, falling back to hardcoded default."""
    value = _resolve_tenant_setting("default_tax_rate_crates")
    return value if value is not None else DEFAULT_CRATE_TAX_RATE


def crates_should_be_on_documents() -> bool:
    """Whether crates are priced and put on delivery notes / invoices for the
    active tenant. Defaults to ``True`` (the model default + the safe fallback
    when there's no tenant context) so existing tenants are unaffected."""
    value = _resolve_tenant_setting("crates_should_be_on_documents")
    return True if value is None else bool(value)


def get_min_weeks_from_creation_to_start_delivery() -> int:
    """Lead time in weeks before a subscription may start, measured from
    "now". Falls back to 0 (no lead-time enforcement) when there's no tenant
    context — e.g. test setup. Mirrors the office UI's ``valid_from`` date
    picker floor (see ``useSubscriptionTerm`` on the frontend)."""
    value = _resolve_tenant_setting("min_weeks_from_creation_to_start_delivery")
    return int(value) if value is not None else 0


# these are for the archivable manager
CUT_OFF_MONTHS = 2
CUT_OFF_DAYS = 30
