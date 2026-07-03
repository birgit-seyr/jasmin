"""Friendly Captcha verification service.

Verifies a frontend-issued FC solution token against Friendly Captcha's
siteverify API. Used by the four anonymous auth endpoints (login,
public-register, password-reset-request, password-reset-confirm) to
block credential-stuffing, reset-email-spam, and registration-spam
before any business logic runs.

Behaviour matrix
----------------

================================  ============================  =====================================
``FRIENDLY_CAPTCHA_ENABLED``      Caller supplies a solution?   Result
================================  ============================  =====================================
``False`` (default, dormant)      —                             No-op. Endpoint runs as before.
``True``                          missing / empty               Raises ``CaptchaVerificationFailed``.
``True``                          present, FC says ``success``  Returns silently.
``True``                          present, FC says NOT success  Raises ``CaptchaVerificationFailed``.
``True``                          present, FC unreachable       **Fail closed** — raises (see below).
================================  ============================  =====================================

Fail-closed on FC outage is deliberate. We treat FC's availability as
part of the auth-flow contract once the flag is on; falling back to
"let everything through" turns an outage into an open door for bots.
If you'd rather degrade differently, write the open-failure branch
explicitly at the call site — don't change this service.

Privacy
-------

We send only the solution token + the configured secret to FC's API,
never the user-typed email or password. FC is also asked NOT to log
the solution (their default).
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings

from apps.accounts.errors import CaptchaVerificationFailed

logger = logging.getLogger("authentication")


def verify_captcha(solution: str | None, *, scope: str) -> None:
    """Verify ``solution`` against the Friendly Captcha siteverify API.

    Parameters
    ----------
    solution:
        The FC solution token submitted by the frontend (the value the
        widget sets in the ``frc-captcha-solution`` field). May be
        ``None`` or empty when the feature flag is off — the caller
        should not pre-validate this, the service handles it.
    scope:
        Free-form label for log lines (e.g. ``"login"``, ``"register"``,
        ``"password_reset_request"``). Lets ops correlate FC rejections
        to which endpoint was hit without inspecting URLs.

    Returns
    -------
    None on success. Raises ``CaptchaVerificationFailed`` on any
    failure path (missing token, FC says invalid, FC unreachable).
    """
    if not getattr(settings, "FRIENDLY_CAPTCHA_ENABLED", False):
        return

    secret = settings.FRIENDLY_CAPTCHA_SECRET
    sitekey = settings.FRIENDLY_CAPTCHA_SITEKEY
    if not secret or not sitekey:
        # Misconfiguration — flag on but creds empty. This is an
        # operator mistake, not a client one. Log loudly so the next
        # restart catches it, then fail closed so we don't silently
        # accept everything.
        logger.error(
            "captcha.misconfigured scope=%s reason=%s",
            scope,
            "FRIENDLY_CAPTCHA_ENABLED=True but sitekey/secret missing",
        )
        raise CaptchaVerificationFailed(
            "Captcha verification is misconfigured. Please contact support."
        )

    if not solution:
        logger.info("captcha.missing scope=%s", scope)
        raise CaptchaVerificationFailed("Captcha solution is required.")

    try:
        resp = requests.post(
            settings.FRIENDLY_CAPTCHA_VERIFY_URL,
            json={
                "solution": solution,
                "secret": secret,
                "sitekey": sitekey,
            },
            timeout=settings.FRIENDLY_CAPTCHA_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        # Network error / timeout — fail closed (see module docstring).
        logger.warning(
            "captcha.unreachable scope=%s error=%s",
            scope,
            exc.__class__.__name__,
        )
        raise CaptchaVerificationFailed(
            "Captcha verification is temporarily unavailable. Please try again."
        ) from exc

    if resp.status_code != 200:
        logger.warning(
            "captcha.bad_status scope=%s status=%s",
            scope,
            resp.status_code,
        )
        raise CaptchaVerificationFailed("Captcha could not be verified.")

    try:
        payload = resp.json()
    except ValueError:
        logger.warning("captcha.bad_response scope=%s", scope)
        raise CaptchaVerificationFailed("Captcha could not be verified.") from None

    if not payload.get("success"):
        # FC reports the failure reason in ``errors`` / ``error_codes``.
        # Log it but DO NOT echo to the client — it can include
        # "secret_invalid" which would leak that our creds are wrong.
        logger.info(
            "captcha.rejected scope=%s codes=%s",
            scope,
            payload.get("errors") or payload.get("error_codes"),
        )
        raise CaptchaVerificationFailed("Captcha verification failed.")
