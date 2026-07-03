"""Two-factor auth (TOTP) service.

All 2FA state lives in ``django_otp``'s ``TOTPDevice`` (the 30-second
RFC 6238 codes) and ``StaticDevice`` (one-shot recovery codes). This
module is the only place the rest of the codebase should touch those
models — keep the views thin and route every flow through here.

Glossary:
    * **Enrolment** — user adds a TOTP device. Two-step: ``start`` creates
      an UNCONFIRMED device + returns the secret as a provisioning URI;
      ``confirm`` verifies the user can read codes off their phone, marks
      the device confirmed, and mints recovery codes.
    * **Verify** — user presents a 6-digit code at login (or a recovery
      code if they lost their phone). The post-password second step.
    * **Challenge token** — short-lived signed JWT bound to (user, tenant,
      ``step="2fa"``) and minted on successful password login when 2FA
      is active. Frontend posts it back with the code to ``/verify/`` and
      gets the real access + refresh JWT.

Login flow:

    POST /api/auth/login/          → { requires_2fa: true, challenge_token }
    POST /api/auth/2fa/verify/     → { access, refresh, user, tenant }

Compared to a one-shot login this trades one extra round-trip for the
property that **a stolen password without the phone is useless**.
"""

from __future__ import annotations

import logging
import secrets
from base64 import b32encode
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from django.conf import settings
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import Token

from ..errors import (
    TwoFactorAlreadyEnrolled,
    TwoFactorChallengeInvalid,
    TwoFactorInvalidCode,
    TwoFactorNotEnrolled,
)
from ..models import JasminUser

logger = logging.getLogger("authentication")


_DEVICE_NAME = "default"
_RECOVERY_CODE_COUNT = 10
_RECOVERY_CODE_BYTES = 5  # 8 base32 chars per code, 10 codes = 80 chars


# --------------------------------------------------------------------------- #
# Read helpers                                                                #
# --------------------------------------------------------------------------- #


def _active_totp(user: JasminUser) -> TOTPDevice | None:
    return TOTPDevice.objects.filter(user=user, confirmed=True).first()


def _unconfirmed_totp(user: JasminUser) -> TOTPDevice | None:
    return TOTPDevice.objects.filter(user=user, confirmed=False).first()


def has_two_factor(user: JasminUser) -> bool:
    """Quick yes/no for the login flow and the profile UI."""
    return _active_totp(user) is not None


@dataclass
class TwoFactorStatus:
    enrolled: bool
    enrolled_at: Any  # datetime | None — TOTPDevice has no ``created_at``, use ``last_used_at`` only
    recovery_codes_remaining: int


def status_for_user(user: JasminUser) -> TwoFactorStatus:
    device = _active_totp(user)
    if not device:
        return TwoFactorStatus(
            enrolled=False, enrolled_at=None, recovery_codes_remaining=0
        )
    static = StaticDevice.objects.filter(user=user, confirmed=True).first()
    remaining = static.token_set.count() if static else 0
    return TwoFactorStatus(
        enrolled=True,
        # TOTPDevice has no creation timestamp by default; expose last_used_at
        # for the UI to show "active since" approximately. Good enough — a
        # real "enrolled at" would need a custom model.
        enrolled_at=getattr(device, "last_used_at", None),
        recovery_codes_remaining=remaining,
    )


# --------------------------------------------------------------------------- #
# Enrolment                                                                   #
# --------------------------------------------------------------------------- #


@dataclass
class EnrolmentStart:
    secret: str
    provisioning_uri: str


def start_enrollment(*, user: JasminUser, issuer: str) -> EnrolmentStart:
    """Create an unconfirmed ``TOTPDevice`` and return its provisioning URI.

    ``issuer`` is shown next to the account name in the authenticator app
    — pass the tenant display name (e.g. "Jasmin — Marillenhof"). The
    frontend renders the URI as a QR code via ``qrcode.react``; we don't
    render server-side so the secret only crosses the wire as text.

    If an unconfirmed device already exists for the user (e.g. they
    started enrolment, never finished, and are starting over), it is
    rotated — the old secret is overwritten so a half-finished QR code
    can't be reused.
    """
    if _active_totp(user) is not None:
        raise TwoFactorAlreadyEnrolled("Two-factor auth is already active.")

    # 20 bytes = 160 bits, RFC 4226's recommendation for HOTP/TOTP secrets.
    raw_secret = secrets.token_bytes(20)
    secret_hex = raw_secret.hex()

    pending = _unconfirmed_totp(user)
    if pending:
        pending.key = secret_hex
        pending.save(update_fields=["key"])
        device = pending
    else:
        device = TOTPDevice.objects.create(
            user=user,
            name=_DEVICE_NAME,
            confirmed=False,
            key=secret_hex,
            step=30,
            digits=6,
            tolerance=1,
        )

    secret_b32 = b32encode(raw_secret).decode("ascii").rstrip("=")
    label = quote(f"{issuer}:{user.email}")
    provisioning_uri = (
        f"otpauth://totp/{label}"
        f"?secret={secret_b32}"
        f"&issuer={quote(issuer)}"
        f"&algorithm=SHA1"
        f"&digits=6"
        f"&period=30"
    )
    logger.info("2fa.enrolment_started user=%s device_id=%s", user.pk, device.pk)
    return EnrolmentStart(secret=secret_b32, provisioning_uri=provisioning_uri)


@dataclass
class EnrolmentResult:
    recovery_codes: list[str]


def confirm_enrollment(*, user: JasminUser, code: str) -> EnrolmentResult:
    """Verify the user can read the 6-digit code and finish enrolment.

    Marks the pending device confirmed, replaces the existing
    ``StaticDevice`` (if any) with a fresh batch of single-use recovery
    codes, and returns those codes as plain strings — caller is
    responsible for showing them to the user exactly once.
    """
    device = _unconfirmed_totp(user)
    if device is None:
        if _active_totp(user) is not None:
            raise TwoFactorAlreadyEnrolled("Two-factor auth is already active.")
        raise TwoFactorNotEnrolled("No pending enrolment for this user.")

    if not device.verify_token(code):
        logger.warning("2fa.enrolment_code_invalid user=%s", user.pk)
        raise TwoFactorInvalidCode("Code did not verify. Try the next one.")

    device.confirmed = True
    device.save(update_fields=["confirmed"])

    codes = _replace_recovery_codes(user)
    logger.info(
        "2fa.enrolled user=%s device_id=%s recovery_codes=%s",
        user.email,
        device.pk,
        len(codes),
    )
    return EnrolmentResult(recovery_codes=codes)


def _replace_recovery_codes(user: JasminUser) -> list[str]:
    """Drop any existing recovery codes and mint a fresh batch."""
    StaticDevice.objects.filter(user=user).delete()
    device = StaticDevice.objects.create(user=user, name="recovery", confirmed=True)
    plain_codes: list[str] = []
    for _ in range(_RECOVERY_CODE_COUNT):
        # 8 base32 chars (no padding) — easy to type, no confusing 0/O/1/I.
        token = (
            b32encode(secrets.token_bytes(_RECOVERY_CODE_BYTES))
            .decode("ascii")
            .rstrip("=")
            .lower()
        )
        StaticToken.objects.create(device=device, token=token)
        plain_codes.append(token)
    return plain_codes


# --------------------------------------------------------------------------- #
# Verify                                                                      #
# --------------------------------------------------------------------------- #


def verify_code(*, user: JasminUser, code: str) -> bool:
    """Verify a 6-digit TOTP code OR a recovery code.

    Returns ``True`` on success, raises ``TwoFactorInvalidCode`` otherwise.
    Recovery codes are consumed — verifying one deletes it.
    """
    if not has_two_factor(user):
        raise TwoFactorNotEnrolled("Two-factor auth is not active for this user.")

    cleaned = (code or "").replace(" ", "").replace("-", "").strip()
    if not cleaned:
        raise TwoFactorInvalidCode("Code is empty.")

    # Try TOTP first (most common path).
    totp = _active_totp(user)
    if totp is not None and totp.verify_token(cleaned):
        logger.info("2fa.verified user=%s method=totp", user.pk)
        return True

    # Recovery codes are stored lowercase — see ``_replace_recovery_codes``.
    static = StaticDevice.objects.filter(user=user, confirmed=True).first()
    if static is not None and static.verify_token(cleaned.lower()):
        logger.info("2fa.recovery_used user=%s", user.pk)
        return True

    logger.warning("2fa.failed user=%s", user.pk)
    raise TwoFactorInvalidCode("Code did not verify.")


# --------------------------------------------------------------------------- #
# Disable + regenerate recovery codes                                         #
# --------------------------------------------------------------------------- #


def disable(*, user: JasminUser, code: str) -> None:
    """Disable 2FA. Requires a valid TOTP or recovery code."""
    verify_code(user=user, code=code)
    TOTPDevice.objects.filter(user=user).delete()
    StaticDevice.objects.filter(user=user).delete()
    logger.info("2fa.disabled user=%s", user.pk)


def regenerate_recovery_codes(*, user: JasminUser, code: str) -> list[str]:
    """Mint a fresh batch of recovery codes. Requires a valid TOTP code."""
    if not has_two_factor(user):
        raise TwoFactorNotEnrolled("Two-factor auth is not active for this user.")
    totp = _active_totp(user)
    if totp is None or not totp.verify_token((code or "").replace(" ", "").strip()):
        # Recovery codes shouldn't be usable here — we're trying to PROVE
        # the user still holds the TOTP device. Anyone with just a
        # recovery code shouldn't be able to lock the real owner out.
        logger.warning("2fa.recovery_regenerate_failed user=%s", user.pk)
        raise TwoFactorInvalidCode("TOTP code required.")
    codes = _replace_recovery_codes(user)
    logger.info("2fa.recovery_codes_regenerated user=%s count=%s", user.pk, len(codes))
    return codes


# --------------------------------------------------------------------------- #
# Challenge tokens                                                            #
# --------------------------------------------------------------------------- #
#
# Between password success and 2FA verification we don't yet have a real
# session. We mint a short-lived signed token bound to (user_id, tenant,
# step="2fa") with a 5-minute expiry, hand it to the frontend, and accept
# it back at /verify/. It's a ``simplejwt`` token so signing key + parsing
# are reused — no separate crypto.


class _ChallengeToken(Token):
    token_type = "two_factor_challenge"  # type: ignore[assignment]
    lifetime = settings.TWO_FACTOR_CHALLENGE_LIFETIME


def issue_challenge_token(*, user: JasminUser, tenant_schema: str) -> str:
    token = _ChallengeToken()
    token["user_id"] = str(user.id)
    token["tenant_id"] = tenant_schema
    token["step"] = "2fa"
    return str(token)


def consume_challenge_token(*, challenge: str, tenant_schema: str) -> JasminUser:
    """Validate a challenge token and return its bound user.

    Raises ``TwoFactorChallengeInvalid`` on any failure — expired,
    malformed, wrong tenant, wrong step, unknown user.
    """
    try:
        token = _ChallengeToken(challenge)
    except TokenError as exc:
        raise TwoFactorChallengeInvalid(str(exc)) from exc

    if token.get("step") != "2fa":
        raise TwoFactorChallengeInvalid("Wrong token type.")
    if token.get("tenant_id") != tenant_schema:
        raise TwoFactorChallengeInvalid("Token does not belong to this tenant.")

    user_id = token.get("user_id")
    user = JasminUser.objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        raise TwoFactorChallengeInvalid("Unknown or inactive user.")
    return user


# --------------------------------------------------------------------------- #
# Enrolment tokens                                                            #
# --------------------------------------------------------------------------- #
#
# When a role MANDATES 2FA (TWO_FACTOR_REQUIRED_ROLES) and the user has no
# device yet, login issues NO session — but enroll-start/confirm need auth, so
# the user would be permanently locked out. We mint a short-lived, scope-
# limited enrolment token (bound to user+tenant, ``step="2fa_enrol"``), like
# the challenge token, that the enrol endpoints accept in place of a session.


class _EnrolmentToken(Token):
    token_type = "two_factor_enrolment"  # type: ignore[assignment]
    lifetime = settings.TWO_FACTOR_ENROLMENT_LIFETIME


def issue_enrolment_token(*, user: JasminUser, tenant_schema: str) -> str:
    token = _EnrolmentToken()
    token["user_id"] = str(user.id)
    token["tenant_id"] = tenant_schema
    token["step"] = "2fa_enrol"
    return str(token)


def consume_enrolment_token(*, enrolment: str, tenant_schema: str) -> JasminUser:
    """Validate an enrolment token and return its bound user. Lets a user
    blocked at login by ``TwoFactorEnrolmentRequired`` reach enroll-start /
    enroll-confirm without a full session. Raises ``TwoFactorChallengeInvalid``
    on any failure — expired, malformed, wrong tenant, wrong step, unknown."""
    try:
        token = _EnrolmentToken(enrolment)
    except TokenError as exc:
        raise TwoFactorChallengeInvalid(str(exc)) from exc

    if token.get("step") != "2fa_enrol":
        raise TwoFactorChallengeInvalid("Wrong token type.")
    if token.get("tenant_id") != tenant_schema:
        raise TwoFactorChallengeInvalid("Token does not belong to this tenant.")

    user = JasminUser.objects.filter(pk=token.get("user_id"), is_active=True).first()
    if user is None:
        raise TwoFactorChallengeInvalid("Unknown or inactive user.")
    return user


# --------------------------------------------------------------------------- #
# Enrolment-required gate (settings-driven)                                   #
# --------------------------------------------------------------------------- #


def role_requires_enrolment(user: JasminUser) -> bool:
    """Does this user's role mandate 2FA enrolment before getting a JWT?"""
    required = set(getattr(settings, "TWO_FACTOR_REQUIRED_ROLES", []) or [])
    if not required:
        return False
    user_roles = set(user.roles or [])
    return bool(required & user_roles)
