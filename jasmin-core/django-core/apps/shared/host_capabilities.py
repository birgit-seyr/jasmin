"""What this deployment of jasmin offers, so the frontend can hide the rest.

Jasmin runs standalone, or inside a host application that installs only part of
it and stands in for the rest with its own features. Such a host names itself in
its Django settings as ``JASMIN_HOST``. Jasmin's own settings don't name one; a
``JASMIN_HOST`` environment variable then can, which previews the embedded mode
on a dev stack, and without either it runs standalone. The host's name stays in
this module: the API reports the capabilities below, and the frontend asks for a
capability, never for a host.

Tapir installs only jasmin's commissioning and tenant apps, routes only their
APIs plus its own login and token refresh, and handles logins, users and data
protection itself. It delivers the weekly share demand as import batches and
keeps no subscriptions in jasmin.

A domain-free module, safe to import from any app.
"""

from __future__ import annotations

import os
from typing import Any

from django.conf import settings
from django.core import checks
from django.core.exceptions import ImproperlyConfigured

STANDALONE = "standalone"
TAPIR = "tapir"
_HOSTS = (STANDALONE, TAPIR)


def _configured_host() -> Any:
    return getattr(settings, "JASMIN_HOST", None) or os.environ.get(
        "JASMIN_HOST", STANDALONE
    )


def _unknown_host_message(host: Any) -> str:
    return f"JASMIN_HOST must be {STANDALONE!r} or {TAPIR!r}, not {host!r}."


def jasmin_host() -> str:
    """The configured host; an unknown name fails loudly rather than letting
    every capability fall back on."""
    host = _configured_host()
    if host not in _HOSTS:
        raise ImproperlyConfigured(_unknown_host_message(host))
    return host


def check_jasmin_host(app_configs: Any = None, **kwargs: Any) -> list[checks.Error]:
    """System check, so an unknown ``JASMIN_HOST`` stops ``migrate`` and
    ``runserver`` instead of failing the first request that reads it."""
    host = _configured_host()
    if host in _HOSTS:
        return []
    return [checks.Error(_unknown_host_message(host), id="jasmin.E001")]


def host_capabilities() -> dict[str, bool]:
    """Every capability, with whether this deployment offers it.

    * ``support_tickets`` — the help button's support tickets (``/api/support/``).
    * ``gdpr`` — the data-protection actions: "My data" with its deletion
      request, and the office's subject access and erasure of a reseller or a
      member (``/api/gdpr/``).
    * ``user_accounts`` — jasmin's own logins: sign-in, registration and
      passwords, the profile, two-factor authentication, logout and the users
      page (``/api/auth/`` beyond login and token refresh).
    * ``operating_mode_choice`` — the office's choice of the operating mode
      (``uploads_weekly_share_amount``); a host that fixes the mode leaves
      nothing to choose, see ``share_demand_is_imported``.
    * ``legal_notice`` — jasmin's own legal notice ("Impressum") and its
      settings; a host publishes its own.
    * ``web_app`` — installing jasmin as an app on a phone or desktop, with its
      icon and short name; jasmin inside a host's page isn't installed on its
      own.
    * ``manual_share_import`` — the office's own upload of the weekly share
      amounts; Tapir imports them on every visit, and a manual import there
      would compete with it.
    * ``about`` — jasmin's footer, its credit line and the "about" dialog
      presenting jasmin's features; inside a host's page jasmin is a part of
      the host and doesn't present itself.
    * ``delivery_stations`` — jasmin's delivery-station pages: the station list,
      the delivery tours, the tour and pickup lists and the station fees, the
      "also a delivery station" flag of resellers and sellers, the crate a
      share size goes out to the stations in, and adding, deleting and
      setting the validity of the share delivery days. Tapir syncs its pickup
      locations into jasmin, with the delivery days they follow from, knows the
      members at each and handles them itself.
    * ``module_choice`` — the office's choice of jasmin's modules
      (``Tenant.navigation``); a host that installs only some of them fixes the
      choice, see ``navigation_in_effect``.
    * ``share_types`` — adding and deleting share types and their sizes,
      renaming a share type, and the share options without any. Tapir syncs
      its product types and products into jasmin as share types and sizes,
      recognises a share type by its name, and ends every one it doesn't have,
      so one added or renamed in jasmin wouldn't last.
    """
    standalone = jasmin_host() == STANDALONE
    return {
        "support_tickets": standalone,
        "gdpr": standalone,
        "user_accounts": standalone,
        "operating_mode_choice": standalone,
        "legal_notice": standalone,
        "web_app": standalone,
        "manual_share_import": standalone,
        "delivery_stations": standalone,
        "about": standalone,
        "module_choice": standalone,
        "share_types": standalone,
    }


def share_demand_is_imported(stored_setting: bool) -> bool:
    """Whether the weekly share demand comes from imported amounts rather than
    from subscriptions: the tenant's ``uploads_weekly_share_amount``, and always
    inside Tapir, whatever is stored."""
    return stored_setting or jasmin_host() == TAPIR


# The modules the office switches on and off in ``Tenant.navigation``, and the
# ones Tapir installs.
_MODULE_FLAGS = (
    "show_members",
    "show_abos",
    "show_commissioning",
    "show_staff",
    "show_warehouse",
    "show_economics",
    "show_cultivation",
)
_TAPIR_MODULE_FLAGS = ("show_commissioning",)


def navigation_in_effect(stored: dict[str, Any]) -> dict[str, Any]:
    """The tenant's module switches in effect: as ``Tenant.navigation`` stores
    them, and inside Tapir only commissioning on, whatever is stored. The other
    modules aren't installed there, and the office has no choice to make."""
    if jasmin_host() != TAPIR:
        return stored
    return {
        **stored,
        **{flag: flag in _TAPIR_MODULE_FLAGS for flag in _MODULE_FLAGS},
    }
