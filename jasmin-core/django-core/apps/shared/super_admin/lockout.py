"""Per-account brute-force lockout for the super-admin login.

The super-admin login authenticates via ``SuperAdmin.check_password`` directly
(not Django's ``authenticate()``), so django-axes — which only hooks
``authenticate()`` — never counts its failures. The ``super_admin_login``
throttle caps attempts PER IP (10/hour), but a distributed / rotating-IP
attacker sidesteps that. This adds a per-ACCOUNT lock: after
``settings.SUPER_ADMIN_LOGIN_MAX_FAILURES`` failures the account is refused for
``settings.SUPER_ADMIN_LOGIN_LOCKOUT_SECONDS``, independent of source IP.

State lives in the Django cache, which is a shared Redis instance across every
gunicorn worker in prod (and survives restarts on the appendonly volume) — the
same store DRF throttles already rely on. No migration; entries auto-expire via
TTL, so a lockout self-heals after the window.

The account key is the submitted email, normalised. Failures are counted even
for a non-existent email so the lock behaves identically whether or not the
account exists (no enumeration oracle). The trade-off — an attacker can lock a
known super-admin's login for the cooldown by feeding wrong passwords — is
acceptable: it is per-account and self-healing, the primary control is still
the nginx IP allowlist, and refusing an online password-guessing attack against
the platform-root credential outweighs a self-clearing login denial.
"""

from __future__ import annotations

from django.conf import settings
from django.core.cache import cache

_FAIL_COUNT_KEY = "super_admin:login:failcount:{email}"
_LOCK_KEY = "super_admin:login:lockuntil:{email}"


def _normalise(email: str | None) -> str:
    return (email or "").strip().lower()


def is_locked(email: str | None) -> bool:
    """True if the account is currently within its lockout window."""
    return cache.get(_LOCK_KEY.format(email=_normalise(email))) is not None


def register_failure(email: str | None) -> None:
    """Count a failed attempt and lock the account once the threshold is hit.

    The counter is seeded with its TTL on the first failure and incremented
    atomically thereafter, so the failure window slides from that first
    failure; the lock, once set, holds for the full lockout window.
    """
    email = _normalise(email)
    window = settings.SUPER_ADMIN_LOGIN_LOCKOUT_SECONDS
    count_key = _FAIL_COUNT_KEY.format(email=email)

    # ``add`` seeds the counter (with its TTL) only if absent; ``incr`` is
    # atomic on the shared cache and preserves the existing TTL.
    cache.add(count_key, 0, timeout=window)
    try:
        count = cache.incr(count_key)
    except ValueError:
        # The key expired between ``add`` and ``incr`` (narrow race). Reseed.
        cache.set(count_key, 1, timeout=window)
        count = 1

    if count >= settings.SUPER_ADMIN_LOGIN_MAX_FAILURES:
        cache.set(_LOCK_KEY.format(email=email), True, timeout=window)


def reset_failures(email: str | None) -> None:
    """Clear the failure count and any lock — called on a successful login."""
    email = _normalise(email)
    cache.delete(_FAIL_COUNT_KEY.format(email=email))
    cache.delete(_LOCK_KEY.format(email=email))
