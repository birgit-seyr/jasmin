"""The sign-in lockout of tenant users, built on django-axes.

axes counts every failed sign-in per (email, client IP): a wrong password at
the login, which ``authenticate()`` reports to it, a wrong code at the login's
2FA step, and a wrong password or code at step-up. Those last two are checked
outside ``authenticate()`` and reported through ``record_failure``. A pair's
count lapses once ``AXES_COOLOFF_TIME`` passes without a new failure; until
then every failure adds to it, however far apart they come.

With ``LOGIN_LOCKOUT_ENABLED`` on (axes' ``AXES_LOCK_OUT_AT_FAILURE``), a pair
whose count reaches ``AXES_FAILURE_LIMIT`` is refused. The views call
``refuse_if_locked`` before they check a password or code, so a refused attempt
is never counted (nor is a refusal by axes' own backend check,
``AXES_RESET_COOL_OFF_ON_FAILURE_DURING_LOCKOUT``), and the lock ends one
cool-off after the failure that set it. The views answer ``AccountLocked``
themselves: axes flags its lock on DRF's ``Request`` wrapper, which
``AxesMiddleware`` never sees. A completed sign-in (as its tokens are issued)
and a successful step-up clear the failures of their own (email, IP) pair; a
completed password reset clears the address's failures from every IP.

Keyed by the client IP, a stranger guessing at an address locks only their own
pair, never the owner's — as long as the backend sees each client's own
address. Where it doesn't (every client of one CDN edge server arriving with the
edge's address), a stranger's failures would lock the address for everyone
behind that edge, its owner included, so the switch ships off. Off, nothing
locks and nothing clears: failures are recorded under (email, IP) until they
lapse, for the burst alert (``apps.accounts.tasks.alert_on_axes_bursts``).

Super-admins sign in on the public schema, where axes has no tables, and have a
lockout of their own (``apps.shared.super_admin.lockout``).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.contrib.auth.signals import user_login_failed
from django_tenants.utils import get_public_schema_name

from apps.shared.request_utils import client_ip
from core.tenant_db import connection

from ..errors import AccountLocked

if TYPE_CHECKING:
    from rest_framework.request import Request

logger = logging.getLogger("authentication")


def axes_username(request: object, credentials: dict[str, Any] | None) -> str | None:
    """The key a failure is counted under (``AXES_USERNAME_CALLABLE``): the
    address in the one case every spelling of it shares; ``None`` when the
    credentials carry none.

    axes asks with the credentials ``authenticate()`` got: its backend's
    pre-check names the address ``email`` (the user model's
    ``USERNAME_FIELD``), the ``user_login_failed`` signal names it
    ``username``. Reading both is what lets the check find the failures.

    The account lookup is ``email__iexact``, which Postgres runs as ``UPPER()``
    of both sides, and ``UPPER()`` folds more than ASCII case: ``ı`` to ``I``,
    ``ſ`` to ``S``, ``ß`` to ``ẞ``. So ``vıctım@example.com`` signs in as
    victim@example.com, and a key that told the two apart would give each
    spelling a lock of its own. ``UPPER()`` maps one letter to one; upper-cased
    the same way — a letter Python would turn into two, as ``ß`` into ``SS``,
    keeps its form — and then lower-cased, every spelling that signs in to one
    account gets one key. The key is still a spelling of the address that
    ``iexact`` matches, which the GDPR export and erasure find the rows by,
    save for an ``İ`` or a Kelvin sign in the local part. An ASCII address
    keys as its lower-case form.

    Cut to the 255 characters ``AccessAttempt.username`` holds: a longer
    address could not be saved, and cut short it still counts.
    """
    if not credentials:
        return None
    value = credentials.get("username") or credentials.get("email")
    if not isinstance(value, str) or not value.strip():
        return None
    upper = "".join(_upper_letter(letter) for letter in value.strip())
    return upper.lower()[:255]


def _upper_letter(letter: str) -> str:
    upper = letter.upper()
    return upper if len(upper) == 1 else letter


def _lockout_on() -> bool:
    """Whether a pair can be locked: axes and ``LOGIN_LOCKOUT_ENABLED`` are on,
    and the request is on a tenant schema. axes keeps its tables in the tenant
    schemas only; a lookup on the public schema fails with a
    ``ProgrammingError``."""
    return bool(
        settings.AXES_ENABLED
        and settings.AXES_LOCK_OUT_AT_FAILURE
        and connection.schema_name != get_public_schema_name()
    )


def refuse_if_locked(request: Request, email: str) -> None:
    """Raise ``AccountLocked`` while ``email`` is locked out from this client's
    IP. A no-op unless the lockout is switched on."""
    if not _lockout_on():
        return
    from axes.handlers.proxy import AxesProxyHandler

    credentials = {"username": email}
    if AxesProxyHandler.is_allowed(request, credentials):
        return
    # The key, as ``axes_reset_username`` takes it to lift the lock by hand.
    logger.warning(
        "login.locked user=%s ip=%s",
        axes_username(request, credentials),
        client_ip(request),
    )
    raise AccountLocked(
        "Too many failed attempts. Try again later or reset your password."
    )


def record_failure(request: Request, email: str) -> None:
    """Count a wrong password or code checked outside ``authenticate()``
    toward the (email, IP) pair, through the ``user_login_failed`` signal axes
    counts a failed ``authenticate()`` by."""
    user_login_failed.send(
        sender=__name__, credentials={"username": email}, request=request
    )


def clear_failures(request: Request, email: str) -> None:
    """Forget the failures recorded for ``email`` from this client's IP, once
    it signed in or stepped up. Those from other IPs stay: they may be someone
    else's guessing, still locked out, and the burst alert reads them.

    Only while the lockout is on. Off, there is no lock to lift, and deleting
    the pair's rows would hide a run of wrong passwords that ended in the right
    one from the burst alert."""
    if not _lockout_on():
        return
    from axes.helpers import get_client_ip_address

    _reset_attempts(email, ip_address=get_client_ip_address(request))


def clear_all_failures(email: str) -> None:
    """Forget the failures recorded for ``email`` from every IP — only while
    the lockout is on, as ``clear_failures``."""
    if not _lockout_on():
        return
    _reset_attempts(email, ip_address=None)


def _reset_attempts(email: str, *, ip_address: str | None) -> None:
    username = axes_username(None, {"username": email})
    if username is None:
        return
    from axes.handlers.proxy import AxesProxyHandler

    AxesProxyHandler.reset_attempts(username=username, ip_address=ip_address)
