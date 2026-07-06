"""Pre-account email-ownership verification for the public registration wizard.

A prospective member proves they control the address they typed BEFORE any
account is created: the wizard requests a short numeric code
(``send_code``), the code is emailed, and the wizard submits it back
(``verify_code``). A successful verification stamps a short-lived
"verified" marker that the final ``register`` call requires — so the
set-password link the registration then emails can only ever go to an
address the applicant actually controls.

State lives in the Django cache (Redis in prod), NOT the database — the
codes are ephemeral and per-attempt. Keys are scoped by tenant schema so
the same address registering at two tenants never collides.
"""

from __future__ import annotations

import logging
import secrets

from django.core.cache import cache
from django.db import connection

logger = logging.getLogger("authentication")

# A code is valid for 15 minutes; once verified, the applicant has 30
# minutes to finish the wizard and submit the register call.
_CODE_TTL_SECONDS = 15 * 60
_VERIFIED_TTL_SECONDS = 30 * 60
# Hard cap on wrong guesses before the code is burned (anti-brute-force;
# the endpoint is also IP-throttled).
_MAX_ATTEMPTS = 5


def _normalise(email: str) -> str:
    return email.strip().lower()


def _code_key(email: str) -> str:
    return f"emailverify:code:{connection.schema_name}:{_normalise(email)}"


def _verified_key(email: str) -> str:
    return f"emailverify:ok:{connection.schema_name}:{_normalise(email)}"


def generate_and_store_code(email: str) -> str:
    """Mint a fresh 6-digit code, store it (resetting any prior attempts),
    and return it so the caller can email it."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    cache.set(_code_key(email), {"code": code, "attempts": 0}, _CODE_TTL_SECONDS)
    return code


def verify_code(email: str, code: str) -> bool:
    """Check a submitted code. On success, burn the code and stamp the
    verified marker. On failure, count the attempt and burn the code once
    ``_MAX_ATTEMPTS`` is reached. Returns whether the code matched."""
    key = _code_key(email)
    entry = cache.get(key)
    if not entry:
        return False
    if entry.get("attempts", 0) >= _MAX_ATTEMPTS:
        cache.delete(key)
        return False
    if str(code).strip() == entry.get("code"):
        cache.delete(key)
        cache.set(_verified_key(email), True, _VERIFIED_TTL_SECONDS)
        return True
    entry["attempts"] = entry.get("attempts", 0) + 1
    cache.set(key, entry, _CODE_TTL_SECONDS)
    return False


def is_email_verified(email: str) -> bool:
    """Whether ``email`` completed the code check within the verified window."""
    return bool(cache.get(_verified_key(email)))


def clear_verified(email: str) -> None:
    """Consume the verified marker (call once the account is created so the
    one verification can't be replayed for a second registration)."""
    cache.delete(_verified_key(email))
