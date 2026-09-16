"""Which tenant emails still go out while onboarding mode is on.

``TenantSettings.onboarding_mode`` is on while the office enters members, coop
shares and subscriptions that already exist outside Jasmin. Those members must
not be emailed about a history they already lived through, so
``EmailService.send_email`` asks :func:`suppressed_by_onboarding_mode` before
every send and, for a suppressed one, records a ``suppressed`` EmailLog row
instead of sending.

Every email is blocked unless it is listed here as still sent, so a slug added
later stays blocked until someone lists it. Still sent:

* login and security emails (:data:`LOGIN_AND_SECURITY_SLUGS`): password
  resets, registration codes, and the invitation and welcome for staff,
  gardener, reseller-customer and self-registered logins;
* reseller and customer documents (:data:`RESELLER_AND_CUSTOMER_SLUGS`);
* GDPR data-subject emails, which run on legal deadlines
  (:data:`GDPR_DATA_SUBJECT_SLUGS`);
* test sends the office makes to check its SMTP setup or a template
  (:attr:`EmailCategory.TEST_SEND`).

``accounts.invitation`` and ``accounts.welcome_user`` are sent both by login
flows and by member flows. A member flow says so by sending with
:attr:`EmailCategory.MEMBER_LIFECYCLE`, which blocks the send whatever the slug.

The flag is read at send time for the sending schema, so it also covers sends
queued on commit and sends a Huey worker makes under ``schema_context`` (where
``connection.tenant`` is a ``FakeTenant``). No current settings row means off.
Platform alerts to ``settings.ADMINS`` don't go through ``EmailService`` and are
not affected.
"""

from __future__ import annotations

from enum import StrEnum

from core.tenant_db import connection


class EmailCategory(StrEnum):
    """What a send is for, where the slug alone doesn't say it."""

    # The slug decides.
    GENERAL = "general"
    # An email about a member's membership, sent by a member flow. Blocked in
    # onboarding mode, also for a slug that login flows share.
    MEMBER_LIFECYCLE = "member_lifecycle"
    # A test the office sends to check its SMTP setup or a template. Always sent.
    TEST_SEND = "test_send"


LOGIN_AND_SECURITY_SLUGS = frozenset(
    {
        "accounts.password_reset",
        "accounts.email_verification_code",
        "accounts.invitation",
        "accounts.welcome_user",
    }
)

RESELLER_AND_CUSTOMER_SLUGS = frozenset(
    {
        "commissioning.offer",
        "commissioning.invoice",
        "commissioning.delivery_note",
        "commissioning.invoice_reminder",
    }
)

GDPR_DATA_SUBJECT_SLUGS = frozenset(
    {
        "gdpr.deletion_confirm",
        "gdpr.deletion_approved",
        "gdpr.deletion_rejected",
        "gdpr.deletion_pending_admin_office",
    }
)

SLUGS_SENT_IN_ONBOARDING_MODE = (
    LOGIN_AND_SECURITY_SLUGS | RESELLER_AND_CUSTOMER_SLUGS | GDPR_DATA_SUBJECT_SLUGS
)


def sent_in_onboarding_mode(slug: str, category: EmailCategory) -> bool:
    """Whether an email with this slug and category still goes out while
    onboarding mode is on."""
    if category == EmailCategory.TEST_SEND:
        return True
    if category == EmailCategory.MEMBER_LIFECYCLE:
        return False
    return slug in SLUGS_SENT_IN_ONBOARDING_MODE


def onboarding_mode_enabled_for_schema(schema_name: str) -> bool:
    """Whether the tenant owning ``schema_name`` is in onboarding mode, read from
    its current ``TenantSettings`` row. False for the public schema, an unknown
    schema and a tenant without a current settings row.

    The active tenant is reused when it owns the schema: a real ``Tenant`` in a
    request, a ``FakeTenant`` under ``schema_context``, which
    ``TenantSettings.get_current_settings`` resolves by schema name.
    """
    from django_tenants.utils import get_public_schema_name

    from .models import Tenant, TenantSettings

    if schema_name == get_public_schema_name():
        return False
    active_tenant = connection.tenant
    if getattr(active_tenant, "schema_name", None) == schema_name:
        settings = TenantSettings.get_current_settings(active_tenant)
    else:
        tenant = Tenant.objects.filter(schema_name=schema_name).first()
        if tenant is None:
            return False
        settings = TenantSettings.get_current_settings(tenant)
    return settings is not None and settings.onboarding_mode


def suppressed_by_onboarding_mode(
    schema_name: str, *, slug: str, category: EmailCategory
) -> bool:
    """Whether a send from ``schema_name`` must be suppressed: the email is not
    one that still goes out in onboarding mode, and the tenant is in it. The
    flag is only read for emails that would be blocked."""
    if sent_in_onboarding_mode(slug, category):
        return False
    return onboarding_mode_enabled_for_schema(schema_name)
