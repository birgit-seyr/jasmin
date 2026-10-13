"""Project-wide, app-independent middlewares: ``Cache-Control: no-store``
on API responses, the ``/health/`` and ``/health/ready/`` probes answered
ahead of tenant resolution, and the request id (with the log filter that
stamps it on every record). Add other generic middlewares here.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar

from django.core.cache import cache
from django.db import DEFAULT_DB_ALIAS, connections
from django.http import HttpRequest, HttpResponse, JsonResponse

# The project-wide error log that LOGGING configures, shared with
# core.exception_handler.
logger = logging.getLogger("jasmin.errors")

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


class ApiNoStoreCacheControlMiddleware:
    """Force ``Cache-Control: no-store, private`` on every ``/api/`` response.

    Defense-in-depth against a shared CDN (Bunny) caching a per-tenant / per-user
    API response and serving it across tenants. Django/DRF sets no
    ``Cache-Control`` on these responses, so a CDN falls back to its OWN default
    caching — and if its cache key ignores the Host header (Bunny's default with
    one pull zone fronting many tenant hostnames), tenant A's cached
    ``/api/tenants/current/`` gets served for tenant B. ``no-store`` tells every
    intermediary (and browser) never to store the response, closing that leak
    regardless of CDN configuration.

    Scoped to ``/api/`` so static, content-hashed assets (``/static/``, which
    ARE identical across tenants and safe to edge-cache) are untouched. Runs on
    the response leg only; adds nothing to request handling cost.
    """

    # The only ``/api/`` responses allowed to keep their own Cache-Control.
    # Both are public branding for the installable web app (the manifest and
    # the launcher icon): no member, user or operational data, fetched by the
    # BROWSER without credentials, and re-requested on every app launch — so
    # ``no-store`` would mean re-downloading the icon forever.
    #
    # They still vary per tenant, so the cross-tenant hazard this middleware
    # exists for is real for them too. That is handled in the views, which
    # mark them ``private`` (browser-only, never a shared cache) rather than
    # ``public``. Keep this an exact-path allowlist, never a prefix — the rest
    # of ``/api/tenants/`` is ordinary tenant data.
    PUBLIC_BRANDING_PATHS = frozenset(
        {
            "/api/tenants/manifest.webmanifest",
            "/api/tenants/app-icon.png",
        }
    )

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if (
            request.path.startswith("/api/")
            and request.path not in self.PUBLIC_BRANDING_PATHS
        ):
            # Overwrite unconditionally — a stray cacheable value from any view
            # or upstream must not survive on a dynamic, tenant-scoped endpoint.
            response["Cache-Control"] = "no-store, private"
        return response


# Bounds each database step of the readiness probe, so a database that hangs
# fails the probe instead of hanging it. libpq takes connect_timeout in whole
# seconds.
READY_DATABASE_TIMEOUT_SECONDS = 3
# The probe key only has to outlive its own write and read.
READY_CACHE_KEY_TTL_SECONDS = 10
# How long a process answers the readiness probe from one check. The probe is
# public and unthrottled; this window keeps a flood of it from opening a
# database connection and writing to Redis on every request.
READY_VERDICT_SECONDS = 2
# How long a probe waits while another thread of its process runs the check.
# Twice the database timeout covers that check's connect and its statement; a
# check still running after that is hung, so the probe answers 503 rather than
# queue behind it.
READY_CHECK_WAIT_SECONDS = 2 * READY_DATABASE_TIMEOUT_SECONDS


def _database_answers() -> bool:
    """Run ``SELECT 1`` on a connection of the probe's own, closed right after.

    Not the request's connection: its limits are sized for real queries and
    would let a hung database hold the probe for most of a minute. The probe's
    ``statement_timeout`` follows the configured options, and the last ``-c``
    wins.
    """
    probe = connections.create_connection(DEFAULT_DB_ALIAS)
    options = probe.settings_dict["OPTIONS"]
    statement_timeout = f"-c statement_timeout={READY_DATABASE_TIMEOUT_SECONDS * 1000}"
    probe.settings_dict = {
        **probe.settings_dict,
        "OPTIONS": {
            **options,
            "connect_timeout": READY_DATABASE_TIMEOUT_SECONDS,
            "options": f"{options.get('options', '')} {statement_timeout}".strip(),
        },
    }
    try:
        with probe.cursor() as cursor:
            cursor.execute("SELECT 1")
            return cursor.fetchone() == (1,)
    finally:
        probe.close()


def _cache_takes_writes() -> bool:
    """Write a probe key through the configured cache and read it back.

    A write, not a PING: at its ``noeviction`` memory cap Redis keeps answering
    PING while it refuses every write. Each probe writes a key of its own, so
    two probes at once never read each other's value, and the key expires by
    itself.
    """
    token = uuid.uuid4().hex
    key = f"health:ready:{token}"
    cache.set(key, token, timeout=READY_CACHE_KEY_TTL_SECONDS)
    return cache.get(key) == token


def _component_ready(component: str, check: Callable[[], bool]) -> bool:
    """Run one readiness check, logging at warning level when it fails."""
    try:
        if check():
            return True
        logger.warning(
            "health.ready.unavailable component=%s reason=unexpected_result", component
        )
    except Exception:
        # Whatever the check raises, the component is not ready: the probe
        # answers 503, never 500.
        logger.warning(
            "health.ready.unavailable component=%s", component, exc_info=True
        )
    return False


class _ReadinessVerdict:
    """The readiness verdict of one process, reused for READY_VERDICT_SECONDS.

    However often the probe is called, each gunicorn worker runs the checks at
    most once per window. One thread checks at a time: a probe that arrives
    during a check waits for its verdict instead of starting another one.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._checked_at: float | None = None
        self._ready = False
        # The component the running check is on, for the log line of a probe
        # that stops waiting for it.
        self._checking: str | None = None

    def current(self) -> bool:
        if not self._lock.acquire(timeout=READY_CHECK_WAIT_SECONDS):
            logger.warning(
                "health.ready.unavailable component=%s reason=check_still_running",
                self._checking or "unknown",
            )
            return False
        try:
            if (
                self._checked_at is None
                or self._clock() - self._checked_at >= READY_VERDICT_SECONDS
            ):
                self._ready = self._check()
                # Timed from the end of the check, so even a slow one is
                # followed by a whole window without a check.
                self._checked_at = self._clock()
            return self._ready
        finally:
            self._lock.release()

    def _check(self) -> bool:
        """Run every check, so the log names each component that failed."""
        ready = True
        try:
            for component, check in (
                ("database", _database_answers),
                ("cache", _cache_takes_writes),
            ):
                self._checking = component
                ready = _component_ready(component, check) and ready
        finally:
            self._checking = None
        return ready


_readiness_verdict = _ReadinessVerdict()


def _readiness_response() -> JsonResponse:
    """200 while the database answers and the cache takes writes, else 503.

    The body never names a failed component: the probe is public.
    """
    if _readiness_verdict.current():
        response = JsonResponse({"status": "ok"})
    else:
        response = JsonResponse({"status": "unavailable"}, status=503)
    # The answer is about now; no cache on the way may keep it.
    response["Cache-Control"] = "no-store"
    return response


class HealthCheckMiddleware:
    """Answer the ``/health/`` probes BEFORE tenant resolution.

    ``/health/`` is the liveness probe: 200 whenever the process serves
    requests, without touching the database or Redis. The Docker HEALTHCHECK
    (``curl localhost:8000/health/``) and the gateway nginx healthcheck
    (``wget 127.0.0.1/health/``) use it. It must not depend on either: an
    outage of the database or of Redis is no fault of this container, and a
    backend marked unhealthy holds back huey, which starts only once the
    backend is healthy.

    ``/health/ready/`` is the readiness probe: 200 while the database answers
    ``SELECT 1`` and the cache takes a write, 503 otherwise. The deploy and
    rollback smoke tests and the uptime monitors use it, because liveness stays
    200 while every real request fails. Anyone can call it, as often as they
    like, so a process answers it from a verdict up to
    ``READY_VERDICT_SECONDS`` old: a flood costs what a flood of liveness
    probes costs, not a database connection per request.

    The probes reach the backend on hosts that map to NO tenant
    (``localhost``, ``127.0.0.1``, the ``jasmin_backend`` upstream name).
    Tenant resolution is subdomain-only: an unrecognized host has
    ``TenantMainMiddleware`` raise "no tenant for hostname" (HTTP 404) before
    any view runs, so a URL route for either probe would never be reached.

    This short-circuits ahead of the tenant middleware: no probe concerns a
    tenant, so both skip tenant resolution and work on every host. Only GET
    and HEAD are probes. Must sit ABOVE
    ``django_tenants.middleware.main.TenantMainMiddleware`` in ``MIDDLEWARE``.
    """

    HEALTH_PATH = "/health/"
    READY_PATH = "/health/ready/"

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.method in ("GET", "HEAD"):
            if request.path == self.HEALTH_PATH:
                return JsonResponse({"status": "ok"})
            if request.path == self.READY_PATH:
                return _readiness_response()
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
