"""``ApiNoStoreCacheControlMiddleware`` — every ``/api/`` response is uncacheable.

Pins the fix for the 2026-07-10 cross-tenant cache incident: one Bunny pull zone
fronts all tenant hostnames, Django set no ``Cache-Control`` on the anonymous
``GET /api/tenants/current/``, so Bunny applied its default caching with a
host-agnostic key and served ONE tenant's response for every hostname. The
middleware stamps ``no-store`` so no shared CDN can cache + cross-serve a
per-tenant API response.

Pure header logic — no DB / tenant setup needed (``RequestFactory`` only builds
the request; the middleware never resolves a tenant).
"""

from __future__ import annotations

from django.http import HttpResponse
from django.test import RequestFactory

from core.middleware import ApiNoStoreCacheControlMiddleware


def _run(response: HttpResponse, path: str) -> HttpResponse:
    middleware = ApiNoStoreCacheControlMiddleware(lambda request: response)
    return middleware(RequestFactory().get(path))


def test_api_path_gets_no_store():
    resp = _run(HttpResponse("x"), "/api/tenants/current/")
    assert resp["Cache-Control"] == "no-store, private"


def test_non_api_path_is_untouched():
    resp = _run(HttpResponse("x"), "/health/")
    assert "Cache-Control" not in resp


def test_overrides_a_preset_cacheable_value():
    # The load-bearing case: a stray cacheable value from any view/upstream must
    # not survive on a dynamic, tenant-scoped endpoint.
    inner = HttpResponse("x")
    inner["Cache-Control"] = "public, max-age=3600"
    resp = _run(inner, "/api/schema/")
    assert resp["Cache-Control"] == "no-store, private"


def test_media_path_is_left_to_nginx():
    # /media/ is tenant-distinct by path (``<schema>/...``), schema-enforced in
    # core/protected_media.py, capability-signed, and nginx owns its response
    # headers. The middleware must NOT touch it — widening the prefix to
    # /media/ would emit a DUPLICATE Cache-Control header. This test fails loudly
    # if someone "helpfully" broadens the match.
    resp = _run(HttpResponse("x"), "/media/kolaleipzig/2026/invoice.pdf")
    assert "Cache-Control" not in resp
