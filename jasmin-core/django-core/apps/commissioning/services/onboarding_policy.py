"""Server-side reading of the tenant's onboarding mode.

``TenantSettings.onboarding_mode`` is on while the office enters members, coop
shares and subscriptions that already exist outside Jasmin. Viewsets and models
read it here and pass explicit keyword arguments to the services; commissioning
helpers that recompute data never read the flag themselves, so flipping it
cannot change how existing data is recomputed. A client-sent "onboarding" field
is never trusted.

Emails are the exception: ``EmailService.send_email`` reads the flag itself at
send time (``apps.shared.tenants.onboarding_emails``) and suppresses every email
that is not listed there as still sent, including sends queued before the switch
and sends from Huey workers. The ``notify`` arguments the viewsets pass keep the
member flows from scheduling their emails at all. Office actions whose whole
purpose is an email to the member are refused up front
(:func:`assert_member_email_action_allowed`).

Mirrors ``waiting_list_policy`` (function module, not a ``*Service`` class).

Default (no current TenantSettings overlay row): onboarding mode OFF, matching
the model field default.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from django.utils import timezone

from core.tenant_db import connection

if TYPE_CHECKING:
    from apps.commissioning.models import Member, Subscription

# How far before the current week a subscription confirmed in onboarding mode
# materialises its share deliveries.
ONBOARDING_BACKFILL_WEEKS = 6


def _settings():
    from apps.shared.tenants.models import TenantSettings

    return TenantSettings.get_current_settings(connection.tenant)


def onboarding_mode_enabled() -> bool:
    """Whether the current tenant is in onboarding mode. False when there is no
    settings overlay yet."""
    overlay = _settings()
    if overlay is None:
        return False
    return overlay.onboarding_mode


def assert_member_email_action_allowed() -> None:
    """Refuse an office action whose whole purpose is an email to the member (a
    portal invitation, a waiting-list spot offer) while onboarding mode is on.
    Call it before the action changes anything: the email would be suppressed,
    and the login, invitation, capacity hold or quota it leaves behind would
    wait for a message that never arrives."""
    if onboarding_mode_enabled():
        from apps.commissioning.errors import EmailActionBlockedInOnboardingMode

        raise EmailActionBlockedInOnboardingMode()


def backfill_earliest_monday() -> datetime.date:
    """The Monday ``ONBOARDING_BACKFILL_WEEKS`` weeks before the current week:
    the earliest delivery week a subscription confirmed in onboarding mode
    materialises."""
    today = timezone.localdate()
    current_monday = today - datetime.timedelta(days=today.weekday())
    return current_monday - datetime.timedelta(weeks=ONBOARDING_BACKFILL_WEEKS)


def confirmation_datetime(
    confirmed_on: datetime.date | None, *, onboarding: bool
) -> datetime.datetime | None:
    """The ``admin_confirmed_at`` for a confirm request's optional
    ``confirmed_at`` date: 12:00 local time on that date, so the local calendar
    day survives any timezone shift. ``None`` when no date was sent.

    Raises ``ConfirmationDateRequiresOnboardingMode`` for a date sent while the
    mode is off, and ``ConfirmationDateInFuture`` for a date after today.
    """
    if confirmed_on is None:
        return None
    from apps.commissioning.errors import (
        ConfirmationDateInFuture,
        ConfirmationDateRequiresOnboardingMode,
    )

    if not onboarding:
        raise ConfirmationDateRequiresOnboardingMode()
    if confirmed_on > timezone.localdate():
        raise ConfirmationDateInFuture()
    return timezone.make_aware(
        datetime.datetime.combine(confirmed_on, datetime.time(12, 0))
    )


def assert_confirmation_not_after_exit(
    member: Member, *, confirmed_at: datetime.datetime | None
) -> None:
    """Refuse to confirm a departed member (or one of their coop shares) on a
    day after their exit date. Without ``confirmed_at`` the confirmation is
    dated today. The member's entry date is taken from the confirmation day and
    may not follow the exit date (``member_cancelled_effective_after_entry``).
    """
    exit_date = member.cancelled_effective_at
    if member.cancelled_at is None or exit_date is None:
        return
    confirmed_on = (
        timezone.localdate(confirmed_at)
        if confirmed_at is not None
        else timezone.localdate()
    )
    if confirmed_on > exit_date:
        from apps.commissioning.errors import ConfirmationDateAfterExit

        raise ConfirmationDateAfterExit(exit_date)


def assert_departed_member_subscription_confirmable(
    subscription: Subscription,
) -> None:
    """Refuse to confirm a subscription of a member who has left unless the
    member is already confirmed and the subscription ends by their exit date.

    Confirming materialises deliveries and charges up to ``valid_until``, so a
    later end would deliver and bill after the exit. A departed member is never
    admitted through a subscription (see ``Subscription._post_confirm``).
    """
    from apps.commissioning.errors import (
        SubscriptionEndsAfterMemberExit,
        SubscriptionMemberNotAdmitted,
    )

    member = subscription.member
    if not member.admin_confirmed:
        raise SubscriptionMemberNotAdmitted()
    exit_date = member.cancelled_effective_at
    if (
        exit_date is None
        or subscription.valid_until is None
        or subscription.valid_until > exit_date
    ):
        raise SubscriptionEndsAfterMemberExit(exit_date)
