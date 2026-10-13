"""Same-origin guard for the endpoints that set, read or rotate a refresh cookie.

Every tenant host and the super-admin host are subdomains of one registrable
domain, so to a browser they are one *site*. The refresh cookies are
``SameSite=Strict``, which keeps them off cross-site requests only: a script on
one tenant host can POST to another host's login, refresh or logout endpoint
and the browser attaches that host's cookie. CORS keeps the script from reading
the answer only while no allowed origin covers the sibling hosts. This guard
refuses the request itself, so neither a CORS slip nor a sibling page can mint,
rotate or revoke another host's session.

The rule, applied by :func:`require_same_origin`:

* ``Sec-Fetch-Site`` present (current browsers send it over HTTPS): only
  ``same-origin`` and ``none`` (a request the user started) pass.
* ``Sec-Fetch-Site`` absent (older browsers): an ``Origin`` other than ``null``
  must name the request's own host. Hostnames compare case-insensitively and
  without the port, because behind the gateway the Host header carries no port
  while a dev origin such as ``http://test.localhost:3000`` does.
* Neither header: passes. A script's cross-origin fetch always carries
  ``Origin``, so this is the test client, curl or a server-side caller, none of
  which holds a browser's cookies for another host.

The request's own host is ``request.get_host()``: the Host header, which
``TenantMainMiddleware`` has already checked against ``ALLOWED_HOSTS``.
``USE_X_FORWARDED_HOST`` is off, so a caller can't substitute its own value
through ``X-Forwarded-Host``.

``settings.AUTH_ORIGIN_GUARD`` switches the guard off, for a proxy that turns
out to strip or rewrite these headers.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Concatenate, ParamSpec, TypeVar
from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpRequest

from apps.shared.errors import CrossOriginRequestRefused
from apps.shared.request_utils import client_ip

logger = logging.getLogger("django.security")

_PASSING_FETCH_SITES = frozenset({"same-origin", "none"})

# Outside a browser both headers are whatever the caller sends, so the log line
# carries a truncated, repr-escaped copy of each.
_MAX_LOGGED_HEADER_CHARS = 200

_P = ParamSpec("_P")
_R = TypeVar("_R")
_RequestT = TypeVar("_RequestT", bound=HttpRequest)


def _hostname(url: str) -> str | None:
    """The lowercased hostname of ``url``, without port or trailing dot.

    ``url`` is an origin (``https://host:port``) or a network location prefixed
    with ``//``. None when it names no host, or a malformed IPv6 literal.
    """
    try:
        hostname = urlsplit(url).hostname
    except ValueError:
        return None
    if not hostname:
        return None
    return hostname.rstrip(".") or None


def _refusal_reason(request: HttpRequest) -> str | None:
    """Why ``request`` has to be refused, or None when it may pass."""
    fetch_site = request.headers.get("Sec-Fetch-Site")
    if fetch_site is not None:
        if fetch_site.strip().lower() in _PASSING_FETCH_SITES:
            return None
        return "fetch_site"
    origin = request.headers.get("Origin")
    if origin is None or origin.strip().lower() == "null":
        return None
    origin_host = _hostname(origin.strip())
    own_host = _hostname(f"//{request.get_host()}")
    if origin_host is not None and origin_host == own_host:
        return None
    return "origin_host"


def _bounded(value: str | None) -> str | None:
    return None if value is None else value[:_MAX_LOGGED_HEADER_CHARS]


def refuse_cross_origin(request: HttpRequest) -> None:
    """Raise :class:`CrossOriginRequestRefused` for a browser request from
    another origin, after logging it to the security log."""
    if not settings.AUTH_ORIGIN_GUARD:
        return
    reason = _refusal_reason(request)
    if reason is None:
        return
    logger.warning(
        "auth.cross_origin_refused reason=%s path=%s host=%s origin=%r "
        "sec_fetch_site=%r ip=%s",
        reason,
        request.path,
        request.get_host(),
        _bounded(request.headers.get("Origin")),
        _bounded(request.headers.get("Sec-Fetch-Site")),
        client_ip(request),
    )
    raise CrossOriginRequestRefused(
        "This endpoint only accepts requests from its own site."
    )


def require_same_origin(
    view: Callable[Concatenate[_RequestT, _P], _R],
) -> Callable[Concatenate[_RequestT, _P], _R]:
    """Run :func:`refuse_cross_origin` before ``view``.

    Goes directly above the ``def``, beneath ``@api_view`` and the class
    decorators, so the refusal reaches the DRF exception handler like any
    other ``JasminError``.
    """

    @functools.wraps(view)
    def guarded(request: _RequestT, /, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        refuse_cross_origin(request)
        return view(request, *args, **kwargs)

    return guarded
