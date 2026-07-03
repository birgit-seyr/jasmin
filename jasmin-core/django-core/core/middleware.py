"""Project-wide middlewares.

Right now this module hosts the request-id middleware. Add other generic,
app-independent middlewares here as they come up.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from contextvars import ContextVar

from django.http import HttpRequest, HttpResponse, JsonResponse

# Header read on inbound (when an upstream sets one) and written on outbound.
# Keeping it standard makes it easy to correlate across services / proxies.
REQUEST_ID_HEADER = "X-Request-ID"

# A ContextVar so any code path — including async, threads spawned by Django,
# Huey tasks invoked synchronously inside a request — can grab the current
# request id without threading it through every function. Loggers can pick
# this up via the ``RequestIdLogFilter`` below.
_request_id_var: ContextVar[str | None] = ContextVar("jasmin_request_id", default=None)


def get_current_request_id() -> str | None:
    """Returns the request id for the current execution context, or None."""
    return _request_id_var.get()


class HealthCheckMiddleware:
    """Answer ``GET /health/`` with 200 BEFORE tenant resolution.

    Liveness probes — the Docker HEALTHCHECK (``curl localhost:8000/health/``),
    the gateway nginx healthcheck (``wget 127.0.0.1/health/``), and the uptime
    monitor — reach the backend on hosts that map to NO tenant (``localhost``,
    ``127.0.0.1``, the ``jasmin_backend`` upstream name). Tenant resolution is
    subdomain-only: an unrecognized host has ``TenantMainMiddleware`` raise
    "no tenant for hostname" (HTTP 404) before any view runs, so registering a
    ``/health/`` URL alone is never reached by those probes.

    This short-circuits ahead of the tenant middleware: a liveness probe only
    needs to know the process is up and serving, not which tenant — so it skips
    tenant/DB resolution entirely and works on every host. Must sit ABOVE
    ``django_tenants.middleware.main.TenantMainMiddleware`` in ``MIDDLEWARE``.
    """

    HEALTH_PATH = "/health/"

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path == self.HEALTH_PATH and request.method in ("GET", "HEAD"):
            return JsonResponse({"status": "ok"})
        return self.get_response(request)


class RequestIdMiddleware:
    """Attach a stable id to every request.

    Order matters: place this NEAR THE TOP of ``MIDDLEWARE`` so the id is
    available to every downstream middleware (including the tenant middleware
    that runs queries). Reads ``X-Request-ID`` from inbound requests if a
    trusted proxy already assigned one; otherwise generates a 12-char hex id
    (full uuid4 is overkill for log correlation and bloats every log line).
    """

    HEX_LENGTH = 12

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = request.META.get(
            f"HTTP_{REQUEST_ID_HEADER.upper().replace('-', '_')}"
        )
        request_id = self._sanitize(incoming) or uuid.uuid4().hex[: self.HEX_LENGTH]
        request.id = request_id  # type: ignore[attr-defined]

        token = _request_id_var.set(request_id)
        try:
            response = self.get_response(request)
        finally:
            _request_id_var.reset(token)

        response[REQUEST_ID_HEADER] = request_id
        return response

    @staticmethod
    def _sanitize(value: str | None) -> str | None:
        """Allow upstream IDs only if they're safe and short.

        We don't trust arbitrary client headers to flow into our logs.
        """
        if not value:
            return None
        value = value.strip()
        if len(value) > 64 or not all(c.isalnum() or c in "-_" for c in value):
            return None
        return value


class RequestIdLogFilter(logging.Filter):
    """Logging filter that injects ``request_id`` onto every LogRecord.

    Wire it into a log handler/formatter to include the id in every log line::

        "filters": {"request_id": {"()": "core.middleware.RequestIdLogFilter"}},
        "handlers": {"console": {"filters": ["request_id"], ...}},
        "formatters": {"verbose": {"format": "{asctime} {request_id} {levelname} {name} {message}"}}
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = get_current_request_id() or "-"
        return True
