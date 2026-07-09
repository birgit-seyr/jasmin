"""Password-reset service.

Modern, library-free implementation built on Django's stateless
``PasswordResetTokenGenerator``:

* Tokens are HMAC-signed and derived from the user's ``last_login`` and the
  current password hash, so they auto-invalidate the moment the user logs in
  or completes a reset. Nothing is stored in the DB.
* Token expiry is governed by ``settings.PASSWORD_RESET_TIMEOUT`` (we set
  this to 1 hour for the reset flow — see ``config/settings.py``).
* The "request" endpoint **always** returns success regardless of whether
  the email exists, to prevent user-enumeration.
* Pending-invitation / pending-approval users are skipped (they should use
  the invitation flow instead) — but the response is still 200.
* Rate-limited at the view layer via DRF's ``ScopedRateThrottle``.

Used by:
- ``POST /api/auth/password-reset/request/``
- ``POST /api/auth/password-reset/confirm/``
"""

from __future__ import annotations

import logging

from django.contrib.auth import password_validation
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.exceptions import ValidationError
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from apps.accounts.errors import InvalidResetLink, WeakPassword
from apps.accounts.models import JasminUser

logger = logging.getLogger("authentication")

# Statuses for which password reset is *not* offered (the user has another
# flow to go through first).
_BLOCKED_STATUSES = {"pending_invitation", "pending_approval"}

token_generator = PasswordResetTokenGenerator()


# --------------------------------------------------------------------------- #
# Request                                                                     #
# --------------------------------------------------------------------------- #


def request_password_reset(*, email: str) -> None:
    """Look up the user and dispatch a reset email. Silent on miss.

    Always returns ``None``. Callers must not branch on the result, because
    we deliberately do not signal whether the email exists.
    """
    if not email:
        return

    email = email.strip().lower()
    user = (
        JasminUser.objects.filter(email__iexact=email, is_active=True)
        .exclude(account_status__in=_BLOCKED_STATUSES)
        .first()
    )
    if user is None:
        # Log for ops, but don't tell the caller.
        logger.info("password_reset.request unknown")
        return

    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = token_generator.make_token(user)

    _send_password_reset_email(user=user, uid=uid, token=token)
    logger.info("password_reset.request sent user=%s", user.pk)


# --------------------------------------------------------------------------- #
# Confirm                                                                     #
# --------------------------------------------------------------------------- #


def confirm_password_reset(*, uid: str, token: str, password: str) -> JasminUser:
    """Validate ``(uid, token)`` and set ``password`` on the user.

    Raises ``InvalidResetLink`` on bad/expired tokens, ``WeakPassword`` when
    the new password fails Django's validators.
    """
    if not uid or not token or not password:
        raise InvalidResetLink("Missing uid, token, or password.")

    try:
        user_id = force_str(urlsafe_base64_decode(uid))
        user = JasminUser.objects.get(pk=user_id)
    except (TypeError, ValueError, OverflowError, JasminUser.DoesNotExist) as exc:
        raise InvalidResetLink("Invalid or expired reset link.") from exc

    if not user.is_active or user.account_status in _BLOCKED_STATUSES:
        raise InvalidResetLink("Invalid or expired reset link.")

    if not token_generator.check_token(user, token):
        raise InvalidResetLink("Invalid or expired reset link.")

    try:
        password_validation.validate_password(password, user=user)
    except ValidationError as exc:
        raise WeakPassword(" ".join(exc.messages), field="password") from exc

    user.set_password(password)
    # Bump ``last_login`` is NOT set here — Django's token generator already
    # invalidates the token because it incorporates the password hash, which
    # has now changed. Single-use is guaranteed.
    user.save(update_fields=["password", "updated_at"])

    # GAP-1: a password reset must kill any live session — a refresh token
    # stolen before the reset (the exact scenario a reset defends against)
    # otherwise stays rotatable for its full lifetime. Revoke all of the
    # user's sessions so the attacker's token can't be refreshed forward.
    from apps.accounts.services.auth_service import revoke_all_sessions

    revoke_all_sessions(user)

    logger.info("password_reset.confirm success user=%s", user.pk)
    return user


# --------------------------------------------------------------------------- #
# Email                                                                       #
# --------------------------------------------------------------------------- #


def _send_password_reset_email(*, user: JasminUser, uid: str, token: str) -> None:
    """Render and dispatch the reset email. Best-effort — failures are
    logged but never raised, because surfacing email errors would leak
    whether the email was on file."""
    from apps.shared.deferred_email import send_email_best_effort
    from apps.shared.tenant_urls import frontend_base_url, tenant_name

    base_url = frontend_base_url()
    reset_url = f"{base_url}/reset-password/{uid}/{token}"

    # Flatten to plain scalars — never hand a live ORM instance to the
    # tenant-editable email renderer (see template_renderer._resolve).
    context = {
        "tenant_name": tenant_name(),
        "user": {"first_name": user.first_name},
        "reset_url": reset_url,
    }
    send_email_best_effort(
        slug="accounts.password_reset",
        to_emails=[user.email],
        context=context,
        related_object_type="user",
        related_object_id=str(user.id),
        language=user.user_language or None,  # EML-9: user's language
        logger=logger,
        log_error_event="password_reset.email_failed",
        log_not_sent_event="password_reset.email_not_sent",
        log_ref=f"user={user.pk}",
    )
