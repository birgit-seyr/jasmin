"""HttpOnly cookie helpers for refresh tokens.

Refresh tokens are stored in HttpOnly, Secure, SameSite=Strict cookies so
that JavaScript (and therefore XSS) cannot read them. Access tokens stay
in the JSON response body and are kept in JS memory only on the client.

Cookies are set host-only (no Domain attribute), which means a cookie set
by `tenant1.mydomain.com` is never sent to `tenant2.mydomain.com` or
`admin.mydomain.com` — browser-enforced tenant isolation.

Each realm uses a distinct Path so the two cookies cannot collide:
  - tenant users:  Path=/api/auth/         cookie name=refresh_token
  - super admins:  Path=/api/super-admin/  cookie name=sa_refresh_token
"""

from __future__ import annotations

from django.conf import settings
from rest_framework.response import Response

TENANT_REFRESH_COOKIE = "refresh_token"
TENANT_REFRESH_COOKIE_PATH = "/api/auth/"

SUPER_ADMIN_REFRESH_COOKIE = "sa_refresh_token"
SUPER_ADMIN_REFRESH_COOKIE_PATH = "/api/super-admin/"


def _max_age_seconds() -> int:
    return int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds())


def _samesite() -> str:
    # Strict in production. In DEBUG, "Lax" so cross-site dev tooling
    # (Vite on a different port/host) still works.
    return "Strict" if not settings.DEBUG else "Lax"


def _set_refresh_cookie(
    response: Response, *, name: str, path: str, token: str
) -> None:
    response.set_cookie(
        key=name,
        value=token,
        max_age=_max_age_seconds(),
        path=path,
        secure=not settings.DEBUG,
        httponly=True,
        samesite=_samesite(),
    )


def _clear_refresh_cookie(response: Response, *, name: str, path: str) -> None:
    # Django's `delete_cookie` defaults `secure=False`, but browsers will
    # silently ignore a deletion whose attributes don't match the cookie
    # being deleted. Our refresh cookies are set with `Secure` in production
    # and `SameSite=Strict`, so we must mirror those here. We use
    # `set_cookie` with an empty value + Max-Age=0 instead of
    # `response.delete_cookie` so we have explicit control over every flag.
    response.set_cookie(
        key=name,
        value="",
        max_age=0,
        expires="Thu, 01 Jan 1970 00:00:00 GMT",
        path=path,
        secure=not settings.DEBUG,
        httponly=True,
        samesite=_samesite(),
    )


# ---- tenant users -----------------------------------------------------------


def set_tenant_refresh_cookie(response: Response, token: str) -> None:
    _set_refresh_cookie(
        response,
        name=TENANT_REFRESH_COOKIE,
        path=TENANT_REFRESH_COOKIE_PATH,
        token=token,
    )


def clear_tenant_refresh_cookie(response: Response) -> None:
    _clear_refresh_cookie(
        response,
        name=TENANT_REFRESH_COOKIE,
        path=TENANT_REFRESH_COOKIE_PATH,
    )


def get_tenant_refresh_token(request) -> str | None:
    return request.COOKIES.get(TENANT_REFRESH_COOKIE)


# ---- super admins -----------------------------------------------------------


def set_super_admin_refresh_cookie(response: Response, token: str) -> None:
    _set_refresh_cookie(
        response,
        name=SUPER_ADMIN_REFRESH_COOKIE,
        path=SUPER_ADMIN_REFRESH_COOKIE_PATH,
        token=token,
    )


def clear_super_admin_refresh_cookie(response: Response) -> None:
    _clear_refresh_cookie(
        response,
        name=SUPER_ADMIN_REFRESH_COOKIE,
        path=SUPER_ADMIN_REFRESH_COOKIE_PATH,
    )


def get_super_admin_refresh_token(request) -> str | None:
    return request.COOKIES.get(SUPER_ADMIN_REFRESH_COOKIE)
