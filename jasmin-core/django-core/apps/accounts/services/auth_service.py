"""Authentication & profile services.

Exceptions raised here (``apps.accounts.errors``) are translated into HTTP
responses by ``core.exception_handler`` — views do not catch them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import update_last_login
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from ..errors import (
    AccountBlocked,
    InvalidCredentials,
    InvalidToken,
    TenantMismatch,
    TwoFactorEnrolmentRequired,
)
from ..models import JasminUser
from . import two_factor_service

logger = logging.getLogger("authentication")


# --------------------------------------------------------------------------- #
# Login                                                                        #
# --------------------------------------------------------------------------- #


_BLOCK_MESSAGES = {
    "pending_approval": (
        "Your account is pending admin approval. Please wait for confirmation."
    ),
    "pending_invitation": "Please check your email to complete registration.",
    "inactive": "Your account has been deactivated. Please contact support.",
}


@dataclass
class LoginResult:
    user: JasminUser
    access: str
    refresh: str
    member_id: str | None
    reseller_id: str | None
    permissions: list[str]


@dataclass
class TwoFactorChallenge:
    """Returned in place of a ``LoginResult`` when the user has 2FA active.

    Frontend posts ``challenge_token`` back to ``/api/auth/2fa/verify/``
    with the 6-digit code to obtain the real access + refresh tokens.
    """

    user: JasminUser
    challenge_token: str


def authenticate_for_tenant(
    *, request, email: str, password: str, tenant
) -> LoginResult | TwoFactorChallenge:
    user = authenticate(request, username=email, password=password)
    if not user:
        raise InvalidCredentials("Invalid credentials")

    # SCO-1 (accepted tradeoff): the branches below return DISTINCT responses
    # for a correct password — account-status (pending / deactivated / check
    # email), a 2FA challenge, or a 403 carrying a short-lived enrolment token.
    # That is a deliberate account-state / 2FA-state oracle: it is reachable
    # ONLY after the right password, behind django-axes lockout (5 fails) + the
    # 20/min login throttle, and the enrolment token is step-scoped + expires in
    # TWO_FACTOR_ENROLMENT_LIFETIME (15m), so an attacker who already knows the
    # password gains only the ability to start a TOTP enrolment (which still
    # can't mint a session). We keep the descriptive responses because they
    # drive the legit-user UX (route to approval / registration / the enrolment
    # wizard). If the oracle ever needs closing, move the status messaging to
    # email and gate enrolment behind an email-confirm link.
    blocker = _BLOCK_MESSAGES.get(user.account_status)
    if blocker:
        raise AccountBlocked(blocker)
    if not user.is_active:
        raise AccountBlocked("Account is disabled")

    # 2FA fork — three states:
    #   1) Active TOTP device  → issue a challenge token, NOT a JWT.
    #   2) No device + role mandates enrolment → 403; frontend routes
    #      the user into the enrolment wizard.
    #   3) No device + role doesn't mandate it → fall through, normal JWT.
    if two_factor_service.has_two_factor(user):
        challenge = two_factor_service.issue_challenge_token(
            user=user, tenant_schema=tenant.schema_name
        )
        return TwoFactorChallenge(user=user, challenge_token=challenge)
    if two_factor_service.role_requires_enrolment(user):
        # The user has NO session yet, but enroll-start/confirm need auth —
        # so hand back a short-lived, scope-limited enrolment token they can
        # present to those endpoints. Without it the gate is a login deadlock.
        raise TwoFactorEnrolmentRequired(
            "Your role requires two-factor authentication. Please enrol to "
            "continue.",
            details={
                "enrolment_token": two_factor_service.issue_enrolment_token(
                    user=user, tenant_schema=tenant.schema_name
                )
            },
        )

    return _issue_login_tokens(user=user, tenant=tenant)


def issue_post_two_factor_tokens(*, user: JasminUser, tenant) -> LoginResult:
    """Mint the real access + refresh tokens after a successful 2FA verify.

    Called by the ``/api/auth/2fa/verify/`` view once the challenge token
    + 6-digit code have validated.
    """
    return _issue_login_tokens(user=user, tenant=tenant)


def _issue_login_tokens(*, user: JasminUser, tenant) -> LoginResult:
    # Stamp ``last_login`` on every successful login (direct + post-2FA). The
    # custom login flow doesn't run through SimpleJWT's
    # ``TokenObtainPairSerializer``, so ``SIMPLE_JWT["UPDATE_LAST_LOGIN"]`` never
    # fires — do it explicitly here, the single chokepoint both success paths
    # share (this runs only after the 2FA-challenge branches have returned).
    update_last_login(None, user)

    refresh = RefreshToken.for_user(user)
    access = refresh.access_token
    access["tenant_id"] = str(tenant.schema_name)
    access["tenant_name"] = str(tenant.name)
    refresh["tenant_id"] = str(tenant.schema_name)
    user_roles = user.roles or ["member"]
    access["user_role"] = user_roles[0] if user_roles else "member"

    try:
        permissions = (
            list(user.get_all_permissions())
            if hasattr(user, "get_all_permissions")
            else []
        )
    except (AttributeError, TypeError):
        # Backend doesn't expose ``get_all_permissions`` or returns
        # something non-iterable — log-and-ignore is enough; the JWT
        # just won't carry permissions.
        permissions = []

    member_profile = getattr(user, "member_profile", None)
    linked_reseller = getattr(user, "linked_reseller", None)

    return LoginResult(
        user=user,
        access=str(access),
        refresh=str(refresh),
        member_id=member_profile.id if member_profile else None,
        reseller_id=linked_reseller.id if linked_reseller else None,
        permissions=permissions,
    )


# --------------------------------------------------------------------------- #
# Refresh                                                                      #
# --------------------------------------------------------------------------- #


def refresh_access_token(
    *,
    refresh_token: str,
    tenant_schema: str | None,
    tenant_name: str | None = None,
) -> dict:
    """Validate refresh token, rotate, return access + new refresh strings."""
    try:
        refresh = RefreshToken(refresh_token)
    except TokenError as exc:
        raise InvalidToken(str(exc)) from exc

    token_tenant = refresh.get("tenant_id")
    if token_tenant is None:
        raise InvalidToken("Missing tenant claim")
    if not tenant_schema:
        # Tenant resolution failed upstream. Fail closed — skipping the
        # binding check here would let a token minted for tenant A be
        # refreshed against any host whose tenant could not be resolved.
        raise InvalidToken("Tenant could not be resolved")
    if token_tenant != tenant_schema:
        raise TenantMismatch("Token does not belong to this tenant")

    # GAP-1 session cut-off: reject any refresh minted before the user last
    # revoked their sessions (password reset / logout-everywhere). Compared
    # against the token's ``iat`` — NOT OutstandingToken membership — so a
    # rotated token (whose new JTI was never registered as outstanding) is
    # still killed. One lookup; skipped entirely when the user never revoked.
    if not _refresh_iat_still_valid(refresh):
        raise InvalidToken("Session has been revoked. Please log in again.")

    # AUTH-2: re-validate the account on every refresh. The GAP-1 iat cut-off
    # above only rejects tokens minted before an EXPLICIT revoke (password reset
    # / logout-all, which stamp ``sessions_revoked_at``); a mid-session admin
    # deactivation stamps nothing, so without this a deactivated user could keep
    # refreshing for the full refresh lifetime. Mirrors the super-admin refresh.
    user = JasminUser.objects.filter(pk=refresh.get("user_id")).first()
    if user is None or not user.is_active:
        raise InvalidToken("User is no longer active. Please log in again.")

    access = refresh.access_token
    # AUTH-5: the access token minted from the refresh carries only claims that
    # live on the REFRESH token (tenant_id). Re-stamp the login-time access
    # claims (tenant_name, user_role) so a refreshed token is claim-identical to
    # a login-minted one — no pre/post-refresh divergence for code reading them.
    access["tenant_id"] = str(tenant_schema)
    if tenant_name is not None:
        access["tenant_name"] = str(tenant_name)
    user_roles = user.roles or ["member"]
    access["user_role"] = user_roles[0] if user_roles else "member"
    new_refresh: RefreshToken | None = None

    if settings.SIMPLE_JWT.get("ROTATE_REFRESH_TOKENS"):
        try:
            if settings.SIMPLE_JWT.get("BLACKLIST_AFTER_ROTATION"):
                refresh.blacklist()
        except AttributeError:
            pass
        refresh.set_jti()
        refresh.set_exp()
        refresh.set_iat()
        new_refresh = refresh

    return {
        "access": str(access),
        "refresh": str(new_refresh) if new_refresh is not None else None,
    }


def _refresh_iat_still_valid(refresh: RefreshToken) -> bool:
    """False when the token was minted before the user's ``sessions_revoked_at``
    cut-off. True when the user never revoked (or the claim is absent).

    ``iat`` is a WHOLE-SECOND POSIX timestamp (floored at mint), so the compare
    is at second granularity: ``int(revoked_at.timestamp())`` truncates the
    cut-off down to its second, and ``iat >= that`` survives. This is what lets
    a user who resets their password and logs in again within the SAME second
    keep their fresh session, while every token from a prior second dies. (A
    token minted in the same second but fractionally BEFORE the revoke also
    survives — a sub-second window with no realistic attacker relevance.)
    """
    user_id = refresh.get("user_id")
    iat = refresh.get("iat")
    if user_id is None or iat is None:
        return True
    revoked_at = (
        JasminUser.objects.filter(pk=user_id)
        .values_list("sessions_revoked_at", flat=True)
        .first()
    )
    if revoked_at is None:
        return True
    return int(iat) >= int(revoked_at.timestamp())


# --------------------------------------------------------------------------- #
# Logout                                                                       #
# --------------------------------------------------------------------------- #


def blacklist_refresh(refresh_token: str) -> None:
    """Best-effort blacklist for logout. Never raises."""
    try:
        token = RefreshToken(refresh_token)
        try:
            token.blacklist()
        except AttributeError:
            pass
    except TokenError:
        pass


def revoke_all_sessions(user: JasminUser) -> None:
    """Invalidate every existing refresh token for ``user`` (GAP-1).

    Used on password reset and "log out everywhere". Two layers:

    * Stamps ``sessions_revoked_at = now`` — the load-bearing guarantee. Every
      refresh (rotated or not) minted before now is rejected by
      ``refresh_access_token`` via the token's ``iat``, so a stolen token can't
      be rotated forward past the credential change.
    * Blacklists the user's known ``OutstandingToken`` rows too, so simplejwt's
      own blacklist check fires and the tables reflect the revocation (the
      timestamp already covers the rotated-current-token that isn't
      outstanding). Best-effort; never the sole guarantee.

    Access tokens already issued keep working until they expire (short-lived,
    ≤ ACCESS_TOKEN_LIFETIME) — that's the inherent JWT window, not widened here.
    """
    from django.utils import timezone

    user.sessions_revoked_at = timezone.now()
    user.save(update_fields=["sessions_revoked_at", "updated_at"])

    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    for outstanding in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=outstanding)


# --------------------------------------------------------------------------- #
# Profile                                                                      #
# --------------------------------------------------------------------------- #


_PROFILE_FIELDS = {"user_language", "first_name", "last_name"}


def update_user_profile(*, user: JasminUser, data: dict[str, Any]) -> list[str]:
    updated = []
    for field in _PROFILE_FIELDS:
        if field in data:
            setattr(user, field, data[field])
            updated.append(field)
    if updated:
        user.save(update_fields=[*updated, "updated_at"])
    return sorted(updated)
