"""Step-up authentication service.

Mints a short-lived "sudo mode" access token that an authenticated
user can use to call irreversible endpoints (GDPR approve-deletion,
super-admin role grant, backup trigger). The token carries a
``step_up_verified_at`` claim; the gated endpoints check freshness via
``apps.accounts.permissions.RequiresStepUp``.

Flow
----

::

    1. Frontend calls a gated endpoint → 403 ``auth.step_up_required``.
    2. Frontend pops a password modal.
    3. Frontend POSTs ``/api/auth/step-up/`` with the password. With
       ``STEP_UP_REQUIRES_TOTP`` on, a user with an active TOTP device
       gets ``auth.two_factor.code_required`` back, and the modal asks for
       the code and POSTs the password with it.
    4. ``verify_and_issue_step_up_token`` returns a fresh access token.
    5. Frontend replaces its in-memory access token + retries the call.

The new access token preserves the carry-along claims from the old
one (``tenant_id`` / ``tenant_name`` / ``user_role`` /
``is_super_admin``) so the rotated token doesn't lose any session
context. We do NOT rotate the refresh token — step-up is a property
of the access token only, and the refresh path is unrelated.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from django.conf import settings
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.errors import (
    InvalidCredentials,
    TwoFactorCodeRequired,
    TwoFactorInvalidCode,
)
from apps.accounts.models import JasminUser

from . import two_factor_service

logger = logging.getLogger("authentication")


# Claims we always copy from the caller's current access token to the
# newly minted step-up token. Anything else on the existing token is
# either auto-managed by simplejwt (jti, exp, iat, token_type) or is
# stale enough that we don't want to copy it without thinking.
_CARRY_CLAIMS = ("tenant_id", "tenant_name", "user_role", "is_super_admin")


def verify_and_issue_step_up_token(
    *,
    user: JasminUser,
    password: str,
    totp_code: str | None,
    current_access_payload: dict[str, Any] | None,
) -> str:
    """Verify password (and optionally TOTP) and mint a step-up token.

    Parameters
    ----------
    user:
        The currently-authenticated user — i.e. ``request.user`` at
        the endpoint. We re-verify their password against the hash
        on the user row rather than calling ``authenticate()``: the
        session already names the user, and the view checks and
        counts the (email, IP) lockout itself (``login_lockout``).
    password:
        The password the user typed into the step-up modal.
    totp_code:
        The 6-digit TOTP code (or a recovery code), when
        ``STEP_UP_REQUIRES_TOTP`` is on and the user has an active
        device. Ignored otherwise.
    current_access_payload:
        Claim dict from the caller's existing access token. Pass
        ``request.auth.payload`` from the view. The carry-along
        claims (``tenant_id``, etc.) are copied to the new token so
        the rotation doesn't lose tenant context.

    Returns
    -------
    The encoded access-token string the frontend should swap in.

    Raises
    ------
    InvalidCredentials
        Password didn't match.
    TwoFactorCodeRequired
        ``STEP_UP_REQUIRES_TOTP=True``, the user has an active device,
        the password matched and no code came with it.
    TwoFactorInvalidCode
        ``STEP_UP_REQUIRES_TOTP=True``, the user has an active device,
        and the code was wrong.
    """
    if not password or not user.check_password(password):
        # Log first, then raise — InvalidCredentials is mapped by the
        # global handler to a canonical Jasmin error response.
        logger.warning(
            "step_up.verify_failed user=%s reason=password",
            user.email,
        )
        raise InvalidCredentials("Incorrect password.")

    if getattr(
        settings, "STEP_UP_REQUIRES_TOTP", False
    ) and two_factor_service.has_two_factor(user):
        if not totp_code:
            # Not a failed attempt: the modal only learns here that this
            # user needs a code.
            raise TwoFactorCodeRequired("Enter the code from your authenticator app.")
        # The verify path of the post-login 2FA flow, so the TOTP and
        # recovery-code semantics stay identical. It raises for a wrong
        # code rather than returning False.
        try:
            two_factor_service.verify_code(user=user, code=totp_code)
        except TwoFactorInvalidCode:
            logger.warning(
                "step_up.verify_failed user=%s reason=totp",
                user.email,
            )
            raise TwoFactorInvalidCode("Invalid two-factor code.") from None

    new_access = AccessToken.for_user(user)
    payload = current_access_payload or {}
    for claim in _CARRY_CLAIMS:
        if claim in payload:
            new_access[claim] = payload[claim]
    # The step-up token ends when the presented one would have: a fresh
    # lifetime would let password-only step-ups keep a session going forever.
    if "exp" in payload:
        new_access["exp"] = payload["exp"]
    new_access["step_up_verified_at"] = int(time.time())

    logger.info(
        "step_up.verified user=%s ttl=%ss",
        user.email,
        settings.STEP_UP_TTL_SECONDS,
    )
    return str(new_access)
