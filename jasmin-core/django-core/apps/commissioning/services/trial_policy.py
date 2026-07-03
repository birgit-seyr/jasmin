"""Server-side enforcement of the tenant's trial-related settings.

The trial-member concept (``Member.is_trial=True``) is fully derived
from the trial-subscription configuration. A
trial member exists for one purpose: to hold a trial subscription
without committing equity first. So:

    Trial-member creation is allowed iff
      allows_trial_subscriptions
      AND allows_trial_subscriptions_for_trial_members.

The full decision tree this module locks into the server:

    Want to create Member(is_trial=True)?
      → check both surviving flags above; reject if either is False.

    Want to create Subscription(is_trial=True)?
      ├── allows_trial_subscriptions=False → reject
      └── True → if member.is_trial AND
                    NOT allows_trial_subscriptions_for_trial_members:
                   reject (trial member can't hold trial sub).
                 else allow.

``Subscription.member`` is ``NOT NULL`` at the ORM layer, so a
Subscription without a Member is structurally impossible — we don't
re-check that.

Defaults (no current TenantSettings overlay row): allow everything.
Freshly-provisioned tenants stay usable before the first config save.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import connection

from ..errors import (
    TrialMembersNotAllowed,
    TrialSubscriptionsNotAllowed,
    TrialSubscriptionsOnlyForFullMembers,
)

if TYPE_CHECKING:
    from apps.commissioning.models import Member


def _settings():
    from apps.shared.tenants.models import TenantSettings

    return TenantSettings.get_current_settings(connection.tenant)


def _trial_members_enabled(overlay) -> bool:
    """The derived "trial-member concept exists" predicate.

    Used in two places:
      * gating Member(is_trial=True) creation
      * gating Subscription(is_trial=True) for a trial-member holder
    """
    return (
        overlay.allows_trial_subscriptions
        and overlay.allows_trial_subscriptions_for_trial_members
    )


def assert_member_creation_allowed(*, is_trial: bool) -> None:
    """Raise ``TrialMembersNotAllowed`` when the tenant has effectively
    turned off the trial-member concept (either by disabling trial
    subscriptions wholesale or by restricting trial subs to full
    members only).

    Non-trial Member creations are unconditionally allowed.
    """
    if not is_trial:
        return
    overlay = _settings()
    if overlay is None:
        return
    if not _trial_members_enabled(overlay):
        raise TrialMembersNotAllowed()


def assert_subscription_creation_allowed(
    *, is_trial: bool, member: Member | None
) -> None:
    """Validate that a Subscription with the given ``is_trial`` /
    ``member`` combination is permitted by tenant policy.

    Two branches:

      * ``is_trial=False`` is unconditionally allowed.
      * ``is_trial=True`` requires ``allows_trial_subscriptions=True``,
        and — if the holding ``member.is_trial=True`` — additionally
        requires ``allows_trial_subscriptions_for_trial_members=True``.

    ``member`` is structurally never None in production (FK NOT NULL),
    but we tolerate it here so callers that haven't fully assembled
    the row yet can pre-check.
    """
    if not is_trial:
        return
    overlay = _settings()
    if overlay is None:
        return
    if not overlay.allows_trial_subscriptions:
        raise TrialSubscriptionsNotAllowed()
    if (
        member is not None
        and member.is_trial
        and not overlay.allows_trial_subscriptions_for_trial_members
    ):
        raise TrialSubscriptionsOnlyForFullMembers()
