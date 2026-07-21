"""Invitation service: provision a user account in `pending_invitation`
state and send them a tokenized email so they can set a password.

Used in two places:
1. **Configuration → Users**: admin creates a tenant staff user (office,
   gardener, …). Standalone — no Member attached.
2. **Members → Send invitation**: admin attaches an account to an existing
   Member who currently has none.

The `accept_invitation()` flow validates the token, runs the project's
configured password validators (zxcvbn entropy ≥ 3), then activates the
user. After acceptance the token is marked used and cannot be replayed.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import timedelta

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.db import OperationalError, ProgrammingError, transaction
from django.utils import timezone
from django.utils.crypto import get_random_string

from apps.accounts.models import JasminUser
from apps.authz.roles import VALID_ROLES, Role
from apps.shared.tenant_urls import frontend_base_url, tenant_name

logger = logging.getLogger("authentication")

# 7 days. Long enough that a user who clicks "later" can still get back in,
# short enough that a leaked invitation isn't useful forever.
INVITATION_TTL = timedelta(days=7)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _tenant_default_language(default: str = "en") -> str:
    """Return the tenant's configured default language, or `default`."""
    from django.db import connection

    schema = getattr(connection, "schema_name", None)
    if not schema or schema == "public":
        return default
    try:
        from apps.shared.tenants.models import Tenant

        tenant = Tenant.objects.get(schema_name=schema)
    except (Tenant.DoesNotExist, OperationalError, ProgrammingError):
        # No tenant row, or DB unreachable / unmigrated. Best-effort
        # lookup → fall back to the caller's default.
        return default
    if getattr(tenant, "tenant_language", None):
        return tenant.tenant_language
    return default


def _normalize_roles(roles: Iterable[str] | None) -> list[str]:
    if not roles:
        return [Role.MEMBER]
    out = [r for r in roles if r in VALID_ROLES]
    return out or [Role.MEMBER]


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #


@transaction.atomic
def create_user_with_invitation(
    *,
    email: str,
    first_name: str,
    last_name: str,
    roles: Iterable[str] | None = None,
    user_language: str | None = None,
    member=None,
    created_by: JasminUser | None = None,
):
    """Create a `pending_invitation` user + UserInvitation, send email.

    Returns ``(user, invitation)``. Raises ``ValidationError`` if the email
    is already taken by an active user.
    """
    from apps.commissioning.models import UserInvitation
    from apps.commissioning.models.choices import InvitationStatus

    email = email.strip().lower()
    existing = JasminUser.objects.filter(email__iexact=email).first()
    if existing and existing.account_status not in (
        "pending_invitation",
        "inactive",
    ):
        raise ValidationError({"email": "A user with this email already exists."})

    # Volume cap on user provisioning. This shared helper is THE choke point for
    # every user-creation path (admin invite, public self-registration, member
    # send-invitation), and each also fires an invite email — so the cap bounds
    # both the account-creation and the email-spam vectors in one place. Placed
    # after the duplicate-email guard so a rejected duplicate doesn't consume
    # quota. No-op off the request path (see enforce_action_quota).
    from apps.shared.tenants.models import RateLimitedAction
    from apps.shared.tenants.rate_limits import enforce_action_quota

    enforce_action_quota(RateLimitedAction.USER_CREATION, actor=created_by)

    user = existing
    if user is None:
        # We need a placeholder password so set_password can be called later.
        # Use a random unusable password until accept_invitation() is hit.
        user = JasminUser.objects.create_user(
            first_name=first_name,
            last_name=last_name,
            email=email,
            password=get_random_string(length=40),
            user_language=user_language or _tenant_default_language(),
            roles=_normalize_roles(roles),
        )
        user.set_unusable_password()
        user.account_status = "pending_invitation"
        user.is_active = False
        user.save(update_fields=["password", "account_status", "is_active"])
    else:
        # Refreshing an invitation for a user who never accepted: roll
        # roles/name forward.
        user.first_name = first_name
        user.last_name = last_name
        user.user_language = (
            user_language or user.user_language or _tenant_default_language()
        )
        user.roles = _normalize_roles(roles)
        user.account_status = "pending_invitation"
        user.is_active = False
        user.set_unusable_password()
        user.save()

    if member is not None and member.user_id is None:
        member.user = user
        member.save(update_fields=["user"])

    # Cancel any still-active invitation for the same user before creating
    # a fresh one — only one valid token at a time.
    UserInvitation.objects.filter(user=user, status=InvitationStatus.SENT).update(
        status=InvitationStatus.CANCELLED
    )

    invitation = UserInvitation.objects.create(
        user=user,
        member=member,
        email=email,
        expires_at=timezone.now() + INVITATION_TTL,
        created_by=created_by,
    )

    _send_invitation_email(user=user, invitation=invitation)

    logger.info(
        "invitation.created user=%s by=%s member=%s",
        user.email,
        getattr(created_by, "email", "system"),
        getattr(member, "id", None),
    )
    return user, invitation


@transaction.atomic
def resend_invitation(*, user: JasminUser, created_by: JasminUser | None = None):
    """Cancel any open invitation, mint a new one, send email."""
    from apps.commissioning.models import UserInvitation
    from apps.commissioning.models.choices import InvitationStatus

    # A resend fires another invite email, so it draws on the same USER_CREATION
    # budget as the initial provisioning — otherwise looping resend_invitation is
    # an uncapped email-bomb / SMTP-reputation vector for a compromised office
    # account (the create path is guarded, this sibling must be too).
    from apps.shared.tenants.models import RateLimitedAction
    from apps.shared.tenants.rate_limits import enforce_action_quota

    enforce_action_quota(RateLimitedAction.USER_CREATION, actor=created_by)

    UserInvitation.objects.filter(user=user, status=InvitationStatus.SENT).update(
        status=InvitationStatus.CANCELLED
    )
    member = getattr(user, "member_profile", None)
    invitation = UserInvitation.objects.create(
        user=user,
        member=member,
        email=user.email,
        expires_at=timezone.now() + INVITATION_TTL,
        created_by=created_by,
    )
    if user.account_status != "pending_invitation":
        user.account_status = "pending_invitation"
        user.is_active = False
        user.save(update_fields=["account_status", "is_active"])
    _send_invitation_email(user=user, invitation=invitation)
    logger.info(
        "invitation.resent user=%s by=%s",
        user.email,
        getattr(created_by, "email", "system"),
    )
    return invitation


def get_invitation(token: str):
    """Look up an invitation by token. Returns the invitation or None.

    Does not reveal whether the token exists vs. is expired vs. is used —
    callers should treat any non-`sent` or expired invitation as invalid
    with the same generic error message.
    """
    from apps.commissioning.models import UserInvitation
    from apps.commissioning.models.choices import InvitationStatus

    try:
        invitation = UserInvitation.objects.select_related("user", "member").get(
            token=token
        )
    except (UserInvitation.DoesNotExist, ValueError):
        return None
    if invitation.status != InvitationStatus.SENT or invitation.is_expired:
        return None
    return invitation


@transaction.atomic
def accept_invitation(*, token: str, password: str) -> JasminUser:
    """Validate the token + password, set password, activate the user.

    Raises ``ValidationError`` (DRF will translate to 400) on:
      * invalid/expired/used token
      * password failing the project validators
    """
    from apps.commissioning.models.choices import InvitationStatus

    invitation = get_invitation(token)
    if invitation is None:
        raise ValidationError({"token": "This invitation link is invalid or expired."})
    user = invitation.user
    if user is None:
        raise ValidationError({"token": "This invitation is no longer valid."})

    # Enforce password rules (incl. zxcvbn entropy ≥ 3 from settings).
    password_validation.validate_password(password, user=user)

    user.set_password(password)
    user.account_status = "active"
    # save() on JasminUser keeps is_active in sync with account_status.
    user.save(update_fields=["password", "account_status", "is_active"])

    invitation.status = InvitationStatus.ACCEPTED
    invitation.save(update_fields=["status"])

    # If the invitation was created in the context of a Member application
    # (Scenario 1: office invites someone they already added as a member),
    # auto-confirm that Member now that the user has actively accepted.
    # The inviter is treated as the confirming admin for audit.
    if invitation.member_id and not invitation.member.admin_confirmed:
        invitation.member.confirm(admin_user=invitation.created_by, save=True)

    # Mark *all other* outstanding invitations for this user as cancelled
    # so a stolen old token cannot be replayed even before its TTL expires.
    from apps.commissioning.models import UserInvitation

    UserInvitation.objects.filter(user=user, status=InvitationStatus.SENT).update(
        status=InvitationStatus.CANCELLED
    )

    # P2-1: account-level welcome. Distinct from
    # ``accounts.application_approved`` (which fires on Member admit
    # — "your membership application was accepted"). This one is the
    # USER-account event — "your login is active, here's the portal".
    # Deferred to on_commit so it never fires for an invitation accept
    # that ends up rolled back.
    _send_welcome_email(user=user)

    logger.info("invitation.accepted user=%s", user.pk)
    return user


# --------------------------------------------------------------------------- #
# Email                                                                       #
# --------------------------------------------------------------------------- #


def _send_invitation_email(*, user: JasminUser, invitation) -> None:
    """Render and dispatch the invitation email.

    Best-effort — failures are logged but do NOT roll back the
    invitation creation, because a missing SMTP server shouldn't lock
    the admin out of the workflow.

    The send is deferred to ``transaction.on_commit`` (P1-3): the public
    callers (`create_user_with_invitation`, `resend_invitation`) run
    inside ``@transaction.atomic``, and we don't want to mail an accept-
    link for an invitation row that ended up rolled back. When called
    outside an atomic block, Django fires the callback immediately, so
    the previous fire-and-forget semantics still hold.
    """
    from apps.shared.deferred_email import schedule_deferred_email

    base_url = frontend_base_url()
    accept_url = f"{base_url}/set-password/{invitation.token}"

    # Flatten to plain scalars — never hand a live ORM instance to the
    # tenant-editable email renderer (see template_renderer._resolve).
    context = {
        "tenant_name": tenant_name(),
        "user": {"first_name": user.first_name, "email": user.email},
        "accept_url": accept_url,
        # EML-4: pre-format to a substitution-safe string (mirrors
        # member_cancellation) so the template needs no Django ``|date`` filter
        # and renders identically under the safe Mustache renderer for overrides.
        "expires_at": (
            invitation.expires_at.strftime("%d.%m.%Y, %H:%M")
            if invitation.expires_at
            else ""
        ),
    }
    user_email = user.email

    # Invitation send must not block the user-creation flow if email is
    # down — the deferred dispatch logs failures and never raises.
    schedule_deferred_email(
        slug="accounts.invitation",
        to_emails=[user_email],
        context=context,
        related_object_type="user",
        related_object_id=str(user.id),
        language=user.user_language or None,  # EML-9: render in the user's language
        logger=logger,
        log_error_event="invitation.email_failed",
        log_not_sent_event="invitation.email_not_sent",
        log_ref=f"user={user_email}",
    )


def _send_welcome_email(*, user: JasminUser) -> None:
    """Dispatch the ``accounts.welcome_user`` email when a user account
    transitions to ``active``.

    Conceptually the USER-account counterpart of
    ``accounts.application_approved`` (which is the MEMBERSHIP event).
    We send this from ``accept_invitation`` because that's the moment
    the password is set and the portal becomes usable. Best-effort,
    deferred via ``on_commit`` so a rolled-back invitation-accept
    never produces a ghost welcome.
    """
    from apps.shared.deferred_email import schedule_deferred_email

    # Flatten to plain scalars — never hand a live ORM instance to the
    # tenant-editable email renderer (see template_renderer._resolve).
    context = {
        "tenant_name": tenant_name(),
        "user": {"first_name": user.first_name},
        "portal_url": frontend_base_url(),
    }
    user_email = user.email

    schedule_deferred_email(
        slug="accounts.welcome_user",
        to_emails=[user_email],
        context=context,
        related_object_type="user",
        related_object_id=str(user.id),
        language=user.user_language or None,  # EML-9: render in the user's language
        logger=logger,
        log_error_event="welcome.email_failed",
        log_not_sent_event="welcome.email_not_sent",
        log_ref=f"user={user_email}",
    )
