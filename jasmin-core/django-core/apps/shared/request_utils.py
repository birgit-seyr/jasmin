"""Tiny request-scoped helpers shared across apps.

Exposes :func:`client_ip`, which extracts the originating client IP from a
DRF / Django ``HttpRequest``, :func:`body`, the typed accessor for an
object-shaped JSON request body, :func:`auth_user`, the typed accessor for the
authenticated user behind a permission-gated endpoint, and
:func:`request_tenant`, the typed accessor for the tenant django-tenants
resolved from the subdomain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.conf import settings
from rest_framework.exceptions import NotAuthenticated

if TYPE_CHECKING:
    from rest_framework.request import Request

    from apps.accounts.models import JasminUser
    from apps.shared.tenants.models import Tenant


def body(request) -> dict[str, Any]:
    """Return the JSON request body as a dict.

    Why this exists
    ---------------
    A JSON request body may legally be an object OR an array::

        {"email": "a@b.c"}      # object -> DRF gives you a dict
        [{"id": 1}, {"id": 2}]  # array  -> DRF gives you a list

    DRF cannot know which one a client will send, so it types ``request.data``
    as ``dict | list | QueryDict``. Writing ``request.data.get("email")`` is
    therefore fine at RUNTIME here — every endpoint in this project documents an
    object body, and no client sends an array — but a type checker has no way to
    know that. All it sees is "this might be a list, and lists have no
    ``.get()``". That single mismatch produced 78 errors, one per body read,
    across 15 files.

    Why a helper instead of silencing it
    ------------------------------------
    The tempting shortcut is to switch the ``union-attr`` check off. Don't: the
    same check is what catches a genuine ``None`` dereference in the models and
    services — the "this foreign key can be null and you didn't check it" case.
    Turning it off to quieten the view layer would blind us exactly where a real
    null-crash lives.

    So instead the body is read in ONE place. The ``isinstance`` test below is a
    type guard: after it, a checker can PROVE the value is a dict, so the
    declared return type holds and every caller's ``.get()`` is unambiguous. No
    suppressions, and one place to change if the rule ever needs to differ.

    What it does at runtime
    -----------------------
    Returns the body when it is an object. Anything else — an array, a bare
    string, or a request with no ``data`` at all — yields an empty dict, so the
    endpoint's own field validation answers with its usual 400 ("this field is
    required") instead of the view raising ``AttributeError`` and returning a
    500. Only a hand-crafted request reaches that branch.
    """
    data = getattr(request, "data", None)
    return data if isinstance(data, dict) else {}


def auth_user(request: Request) -> JasminUser:
    """Return the signed-in user behind a permission-gated endpoint.

    Why this exists
    ---------------
    ``request.user`` is ``JasminUser | AnonymousUser`` — DRF populates it before
    permissions run, and an unauthenticated request carries the anonymous
    sentinel. A view sitting behind ``IsAuthenticated`` / ``IsAdmin`` / a role
    permission can only ever see the real user, but the union is what the
    annotation says, so every ``request.user.email`` and every
    ``service(actor=request.user)`` reads as a possible ``AnonymousUser``.
    ``AnonymousUser`` has no ``email``, no ``roles``, and is not a row any
    ``user=`` lookup can match — 33 reports across 9 modules, all of them the
    same false positive.

    Why a helper instead of a cast
    ------------------------------
    A cast asserts the claim; this proves it. ``is_authenticated`` is the
    documented discriminator between the two classes (``Literal[True]`` on real
    users, ``Literal[False]`` on the anonymous one), so the check below narrows
    the union for real — and if a caller is ever moved behind ``AllowAny``, the
    endpoint answers ``401`` instead of raising ``AttributeError`` at whatever
    line first touches ``.email``.

    Use it wherever the endpoint requires a login. Endpoints that legitimately
    serve anonymous callers keep reading ``request.user`` and branching on it.
    """
    user = request.user
    if not user.is_authenticated:
        raise NotAuthenticated
    return user


def request_tenant(request: Any) -> Tenant:
    """Return the tenant ``TenantMainMiddleware`` resolved for this request.

    django-tenants attaches the resolved ``Tenant`` row to the request before
    any view runs (a subdomain it cannot resolve never reaches one), and DRF's
    ``Request`` forwards the read to the underlying ``HttpRequest``. Neither
    library declares the attribute, so ``request.tenant`` reads as missing.

    Reading it through here also keeps it distinct from ``connection.tenant``,
    which is the *active schema's* tenant and can be a django-tenants
    ``FakeTenant`` outside the HTTP cycle — see ``core.tenant_db``.

    ``request`` is untyped for the same reason the attribute needs this helper:
    neither ``HttpRequest`` nor DRF's ``Request`` declares ``tenant``, so the
    undeclared read is confined to this one line instead of every call site.
    """
    return request.tenant


def client_ip(request) -> str:
    """Return the originating client IP, honoring ``X-Forwarded-For``.

    The gateway nginx appends the real client IP to any client-supplied
    ``X-Forwarded-For`` (``$proxy_add_x_forwarded_for``), so the trusted
    value is the entry ``TRUSTED_PROXY_COUNT`` positions FROM THE RIGHT —
    NOT the leftmost entry, which the client fully controls. Reading the
    leftmost entry let an attacker forge the IP recorded in the
    security / consent / GDPR audit trails. This mirrors DRF's
    ``NUM_PROXIES`` and axes' ``AXES_IPWARE_PROXY_COUNT`` (all driven by
    ``TRUSTED_PROXY_COUNT``) so the recorded forensic IP matches the value
    used for throttle / lockout keying.

    Falls back to ``REMOTE_ADDR`` and finally to an empty string if the
    request is missing (e.g. when an auditlog signal fires outside an HTTP
    cycle).
    """
    if request is None:
        return ""
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        parts = [part.strip() for part in xff.split(",") if part.strip()]
        if parts:
            proxy_count = getattr(settings, "TRUSTED_PROXY_COUNT", 1) or 1
            return parts[-min(proxy_count, len(parts))]
    return request.META.get("REMOTE_ADDR", "")
