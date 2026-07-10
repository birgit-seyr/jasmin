"""Domain errors raised by the accounts app.

The DRF exception handler (``core.exception_handler``) translates these into
the canonical JSON response automatically — views do not need to catch them.

Naming convention for ``code``: ``"<domain>.<reason>"``. Codes are part of
the public API contract; rename only when the meaning genuinely changes.
"""

from __future__ import annotations

from core.errors import AuthError as _AuthError
from core.errors import BadRequestError, ForbiddenError, NotFoundError

# --------------------------------------------------------------------------- #
# Authentication                                                              #
# --------------------------------------------------------------------------- #


class AuthError(_AuthError):
    """Base for every auth-flow failure (login, refresh, token verify)."""

    code = "auth.error"


class InvalidCredentials(AuthError):
    """Wrong email/password.

    We deliberately return 400 (not the HTTP-standard 401) because the
    existing frontend contract treats 401 as "session expired, try silent
    refresh". Surfacing wrong credentials as 401 would trigger the refresh
    interceptor and mask the real failure.
    """

    code = "auth.invalid_credentials"
    http_status = 400


class AccountBlocked(AuthError):
    """Wrong account status for login (pending / inactive)."""

    code = "auth.account_blocked"
    http_status = 403


class SelfRegistrationDisabled(AuthError):
    """Public self-registration is off for this tenant (TenantSettings
    ``allows_self_registration`` is False). The register endpoints refuse so the
    control is real, not only a hidden button."""

    code = "auth.self_registration_disabled"
    http_status = 403


class TenantMismatch(AuthError):
    code = "auth.tenant_mismatch"


class InvalidToken(AuthError):
    code = "auth.invalid_token"


class MissingCredentials(_AuthError):
    """Login payload is missing email or password — input validation, not auth."""

    code = "auth.missing_fields"
    http_status = 400


class TenantMissing(_AuthError):
    """Request did not resolve to a tenant (wrong host or public schema)."""

    code = "auth.tenant_missing"
    http_status = 400


class RefreshTokenMissing(_AuthError):
    """No refresh cookie on the request."""

    code = "auth.refresh_missing"
    http_status = 401


class InvitationInvalid(NotFoundError):
    """Invitation token does not resolve to a pending invitation."""

    code = "invitation.invalid"


# --------------------------------------------------------------------------- #
# Registration                                                                #
# --------------------------------------------------------------------------- #


class RegistrationError(BadRequestError):
    code = "registration.failed"


class RegistrationCodeInvalid(BadRequestError):
    """The email-verification code the applicant submitted is wrong or has
    expired (or too many attempts burned it)."""

    code = "registration.invalid_code"


class RegistrationEmailNotVerified(BadRequestError):
    """A register call arrived for an address that never completed the
    email-ownership code check (or the verified window elapsed)."""

    code = "registration.email_not_verified"


# --------------------------------------------------------------------------- #
# Admin user management                                                       #
# --------------------------------------------------------------------------- #


class AdminUserError(BadRequestError):
    """Generic admin-user validation failure (roles, status, links)."""

    code = "admin_user.invalid"


class UserNotFound(NotFoundError):
    code = "admin_user.not_found"


class UserNotPendingInvitation(BadRequestError):
    code = "admin_user.not_pending_invitation"


# --------------------------------------------------------------------------- #
# Password reset                                                              #
# --------------------------------------------------------------------------- #


class InvalidResetLink(BadRequestError):
    code = "password_reset.invalid_link"


class WeakPassword(BadRequestError):
    code = "password_reset.weak_password"


# --------------------------------------------------------------------------- #
# Step-up authentication                                                      #
# --------------------------------------------------------------------------- #


class StepUpRequired(ForbiddenError):
    """Endpoint requires a fresh step-up authentication.

    Raised by ``apps.accounts.permissions.RequiresStepUp`` when the
    caller's access token has no ``step_up_verified_at`` claim, or the
    claim is older than ``settings.STEP_UP_TTL_SECONDS``. The frontend
    is expected to intercept this code, pop a password modal, call
    ``POST /api/auth/step-up/``, and retry the original request with
    the rotated access token.

    The ``details`` payload carries ``ttl_seconds`` so the frontend
    can render a "valid for 5 min" hint without hard-coding the value.
    """

    code = "auth.step_up_required"
    http_status = 403


# --------------------------------------------------------------------------- #
# Friendly Captcha (bot/abuse protection on public endpoints)                 #
# --------------------------------------------------------------------------- #


class CaptchaVerificationFailed(BadRequestError):
    """Friendly Captcha solution missing, invalid, or unverifiable.

    Raised by ``friendly_captcha_service.verify_captcha`` when
    ``FRIENDLY_CAPTCHA_ENABLED`` is on and the supplied solution token
    fails the FC siteverify check (or the FC API is unreachable inside
    the configured timeout — we fail closed). When the feature flag is
    off, the verifier is a no-op and this is never raised.
    """

    code = "captcha.verification_failed"


# --------------------------------------------------------------------------- #
# Profile                                                                     #
# --------------------------------------------------------------------------- #


class ProfilePermissionDenied(ForbiddenError):
    code = "profile.permission_denied"


# --------------------------------------------------------------------------- #
# Two-factor auth                                                             #
# --------------------------------------------------------------------------- #


class TwoFactorNotEnrolled(AuthError):
    """Caller asked for a 2FA op but the user has no active TOTP device."""

    code = "auth.two_factor.not_enrolled"
    http_status = 400


class TwoFactorAlreadyEnrolled(AuthError):
    """Enrolment requested but the user already has an active TOTP device."""

    code = "auth.two_factor.already_enrolled"
    http_status = 400


class TwoFactorInvalidCode(AuthError):
    """The supplied 6-digit code (or recovery code) did not verify."""

    code = "auth.two_factor.invalid_code"
    http_status = 400


class TwoFactorChallengeInvalid(AuthError):
    """The challenge token is expired, malformed, or for the wrong user."""

    code = "auth.two_factor.challenge_invalid"
    http_status = 400


class TwoFactorEnrolmentRequired(AuthError):
    """User's role mandates 2FA enrolment (settings flag) but they haven't.

    Login should not issue a JWT — frontend must route the user into
    enrolment first.
    """

    code = "auth.two_factor.enrolment_required"
    http_status = 403


__all__ = [
    "AuthError",
    "InvalidCredentials",
    "AccountBlocked",
    "TenantMismatch",
    "InvalidToken",
    "MissingCredentials",
    "TenantMissing",
    "RefreshTokenMissing",
    "InvitationInvalid",
    "RegistrationError",
    "AdminUserError",
    "UserNotFound",
    "UserNotPendingInvitation",
    "InvalidResetLink",
    "WeakPassword",
    "CaptchaVerificationFailed",
    "StepUpRequired",
    "ProfilePermissionDenied",
    "TwoFactorNotEnrolled",
    "TwoFactorAlreadyEnrolled",
    "TwoFactorInvalidCode",
    "TwoFactorChallengeInvalid",
    "TwoFactorEnrolmentRequired",
]
