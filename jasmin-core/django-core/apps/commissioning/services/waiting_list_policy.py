"""Server-side enforcement of the tenant's waiting-list setting.

``TenantSettings.allows_waiting_list_for_subscriptions`` gates the ENTIRE
waiting-list flow: queuing a subscription, offering a freed spot, and the
member-facing accept/decline of an offer. When it is False the tenant has no
waiting list — an at-capacity share type is simply unavailable (the normal
capacity gate's 409 stands) and no offers can exist.

Mirrors ``trial_policy`` (function-module, not a ``*Service`` class).

Default (no current TenantSettings overlay row): waiting list ENABLED — a
freshly-provisioned tenant keeps the historical behaviour before its first
config save, matching the model default of ``True``.
"""

from __future__ import annotations

from django.db import connection

from ..errors import WaitingListDisabled


def _settings():
    from apps.shared.tenants.models import TenantSettings

    return TenantSettings.get_current_settings(connection.tenant)


def waiting_list_enabled() -> bool:
    """Whether the current tenant's waiting list is on. Defaults to True when
    there is no settings overlay yet (matches the model field default)."""
    overlay = _settings()
    if overlay is None:
        return True
    return overlay.allows_waiting_list_for_subscriptions


def assert_waiting_list_enabled() -> None:
    """Raise ``WaitingListDisabled`` when the tenant has turned the waiting list
    off. Call from every behavioural waiting-list entry point (enqueue, offer,
    accept/decline)."""
    if not waiting_list_enabled():
        raise WaitingListDisabled()
