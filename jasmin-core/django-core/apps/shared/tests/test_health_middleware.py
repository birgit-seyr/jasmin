"""The /health/ probes answer ahead of tenant resolution.

Tenant resolution is subdomain-only, with no "no-tenant" fallback: an
unrecognized host has TenantMainMiddleware raise "no tenant for hostname"
(HTTP 404) before any view runs. The Docker HEALTHCHECK and the gateway nginx
healthcheck hit /health/, the deploy and rollback smoke tests and the uptime
monitors /health/ready/ — all on hosts that map to no tenant (localhost,
127.0.0.1, the upstream name) — so both probes must be answered AHEAD of the
tenant middleware.

These tests drive the full middleware stack with hosts no tenant resolves.
``jasmin_backend``, the Host the gateway's /health/ locations send, is not even
a valid host name: anything on the way that called ``get_host()`` would turn
the answer into a 400.

/health/ is liveness: 200 with no DB or tenant context. Its tests run without
the django_db mark, so pytest-django fails any database access they make.
/health/ready/ is readiness: 200 while the database answers and the cache
takes a write, 503 otherwise, with the failing component named in a warning
log line and never in the body. Anyone can call it, so a process reuses its
verdict for READY_VERDICT_SECONDS and a flood never reaches the database or
Redis more than once per window. That verdict lives as long as the process,
so every test here gets a fresh one, on a clock only the test moves.
"""

from __future__ import annotations

import copy
import logging
import threading
from unittest import mock

import pytest
from django.core.cache import cache
from django.db import DEFAULT_DB_ALIAS, OperationalError, connections
from django.db.backends.base.base import BaseDatabaseWrapper
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import OutOfMemoryError

from core import middleware
from core.middleware import (
    READY_CACHE_KEY_TTL_SECONDS,
    READY_DATABASE_TIMEOUT_SECONDS,
    READY_VERDICT_SECONDS,
)

READY_PATH = "/health/ready/"
# The Host the gateway's ``location /health/`` blocks send: the upstream name.
GATEWAY_HOST = "jasmin_backend"


class ManualClock:
    """A monotonic clock that stands still until a test sets ``now``."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def verdict_clock(monkeypatch) -> ManualClock:
    clock = ManualClock()
    monkeypatch.setattr(
        middleware, "_readiness_verdict", middleware._ReadinessVerdict(clock)
    )
    return clock


def test_health_returns_200_on_unresolvable_host(client):
    resp = client.get("/health/", HTTP_HOST="nonexistent.invalid")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_head_returns_200_on_unresolvable_host(client):
    resp = client.head("/health/", HTTP_HOST="nonexistent.invalid")
    assert resp.status_code == 200


def test_health_stays_200_while_the_cache_fails(client):
    # No django_db mark either, so a database access would fail the test too.
    with (
        mock.patch.object(cache, "set", side_effect=RedisConnectionError("refused")),
        mock.patch.object(cache, "get", side_effect=RedisConnectionError("refused")),
    ):
        resp = client.get("/health/", HTTP_HOST=GATEWAY_HOST)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def _failed_components(caplog) -> list[str]:
    """The components the probe's warning lines name, in order."""
    return [
        record.getMessage().split("component=")[1].split()[0]
        for record in caplog.records
        if record.levelno == logging.WARNING
        and record.getMessage().startswith("health.ready.unavailable ")
    ]


@pytest.mark.django_db
class TestReadiness:
    @pytest.mark.parametrize("host", [GATEWAY_HOST, "localhost", "nonexistent.invalid"])
    def test_200_while_database_and_cache_work(self, client, caplog, host):
        resp = client.get(READY_PATH, HTTP_HOST=host)
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        assert resp["Cache-Control"] == "no-store"
        assert _failed_components(caplog) == []

    def test_head_is_a_probe(self, client):
        resp = client.head(READY_PATH, HTTP_HOST=GATEWAY_HOST)
        assert resp.status_code == 200

    def test_503_when_a_database_cursor_raises(self, client, caplog):
        with mock.patch.object(
            BaseDatabaseWrapper,
            "cursor",
            side_effect=OperationalError("server closed the connection unexpectedly"),
        ):
            resp = client.get(READY_PATH, HTTP_HOST=GATEWAY_HOST)
        assert resp.status_code == 503
        assert resp.json() == {"status": "unavailable"}
        assert resp["Cache-Control"] == "no-store"
        assert _failed_components(caplog) == ["database"]

    def test_503_when_the_database_refuses_connections(self, client, caplog):
        # A real connection attempt, to a port nothing listens on.
        with mock.patch.dict(
            connections.settings[DEFAULT_DB_ALIAS], {"HOST": "127.0.0.1", "PORT": "1"}
        ):
            resp = client.get(READY_PATH, HTTP_HOST=GATEWAY_HOST)
        assert resp.status_code == 503
        assert resp.json() == {"status": "unavailable"}
        assert _failed_components(caplog) == ["database"]

    @pytest.mark.parametrize(
        ("method", "error"),
        [
            # Redis over its noeviction memory cap: PING still answers, writes don't.
            (
                "set",
                OutOfMemoryError("command not allowed when used memory > 'maxmemory'."),
            ),
            ("get", RedisConnectionError("Error 111 connecting to redis:6379.")),
        ],
    )
    def test_503_when_the_cache_raises(self, client, caplog, method, error):
        with mock.patch.object(cache, method, side_effect=error):
            resp = client.get(READY_PATH, HTTP_HOST=GATEWAY_HOST)
        assert resp.status_code == 503
        assert resp.json() == {"status": "unavailable"}
        assert _failed_components(caplog) == ["cache"]

    @pytest.mark.parametrize("read_back", [None, "another value"])
    def test_503_when_the_cache_reads_back_another_value(
        self, client, caplog, read_back
    ):
        with mock.patch.object(cache, "get", return_value=read_back):
            resp = client.get(READY_PATH, HTTP_HOST=GATEWAY_HOST)
        assert resp.status_code == 503
        assert resp.json() == {"status": "unavailable"}
        assert _failed_components(caplog) == ["cache"]

    def test_logs_every_failed_component_and_shows_none(self, client, caplog):
        with (
            mock.patch.object(
                BaseDatabaseWrapper, "cursor", side_effect=OperationalError("down")
            ),
            mock.patch.object(cache, "set", side_effect=RedisConnectionError("down")),
        ):
            resp = client.get(READY_PATH, HTTP_HOST=GATEWAY_HOST)
        assert resp.status_code == 503
        assert resp.json() == {"status": "unavailable"}
        assert _failed_components(caplog) == ["database", "cache"]

    def test_the_database_probe_has_its_own_short_lived_connection(self, client):
        configured_options = copy.deepcopy(
            connections.settings[DEFAULT_DB_ALIAS]["OPTIONS"]
        )
        probes = []
        create_connection = connections.create_connection

        def record_probe(alias):
            probe = create_connection(alias)
            probes.append(probe)
            return probe

        with mock.patch.object(
            connections, "create_connection", side_effect=record_probe
        ):
            resp = client.get(READY_PATH, HTTP_HOST=GATEWAY_HOST)

        assert resp.status_code == 200
        [probe] = probes
        assert probe.connection is None, "the probe closes its connection"
        assert (
            probe.settings_dict["OPTIONS"]["connect_timeout"]
            == READY_DATABASE_TIMEOUT_SECONDS
        )
        # The connections real requests open keep the configured limits.
        assert connections.settings[DEFAULT_DB_ALIAS]["OPTIONS"] == configured_options
        # PostgreSQL applies the probe's statement_timeout, not the configured one.
        try:
            with probe.cursor() as cursor:
                cursor.execute("SHOW statement_timeout")
                assert cursor.fetchone() == (f"{READY_DATABASE_TIMEOUT_SECONDS}s",)
        finally:
            probe.close()

    def test_the_cache_probe_key_expires_by_itself(self, client):
        with mock.patch.object(cache, "set", wraps=cache.set) as cache_set:
            resp = client.get(READY_PATH, HTTP_HOST=GATEWAY_HOST)
        assert resp.status_code == 200
        assert cache_set.call_args.kwargs["timeout"] == READY_CACHE_KEY_TTL_SECONDS

    def test_post_is_not_a_probe(self, client):
        resp = client.post(READY_PATH, HTTP_HOST="localhost")
        # A probe answers 200 or 503; a POST goes on to tenant resolution.
        assert resp.status_code not in (200, 503)

    def test_a_flood_of_probes_checks_once_per_window(self, client, verdict_clock):
        with (
            mock.patch.object(
                connections, "create_connection", wraps=connections.create_connection
            ) as create_connection,
            mock.patch.object(cache, "set", wraps=cache.set) as cache_set,
        ):
            for _ in range(20):
                assert client.get(READY_PATH, HTTP_HOST=GATEWAY_HOST).status_code == 200
            verdict_clock.now = READY_VERDICT_SECONDS - 0.5
            assert client.head(READY_PATH, HTTP_HOST=GATEWAY_HOST).status_code == 200
            assert create_connection.call_count == 1
            assert cache_set.call_count == 1

            verdict_clock.now = READY_VERDICT_SECONDS
            assert client.get(READY_PATH, HTTP_HOST=GATEWAY_HOST).status_code == 200
            assert create_connection.call_count == 2
            assert cache_set.call_count == 2

    def test_a_503_holds_until_its_window_ends(self, client, caplog, verdict_clock):
        with mock.patch.object(
            BaseDatabaseWrapper, "cursor", side_effect=OperationalError("down")
        ):
            assert client.get(READY_PATH, HTTP_HOST=GATEWAY_HOST).status_code == 503
        # The database answers again, but the verdict stands for its window.
        verdict_clock.now = READY_VERDICT_SECONDS - 0.5
        assert client.get(READY_PATH, HTTP_HOST=GATEWAY_HOST).status_code == 503
        verdict_clock.now = READY_VERDICT_SECONDS
        assert client.get(READY_PATH, HTTP_HOST=GATEWAY_HOST).status_code == 200
        # One check failed, so one warning, however many probes it answered.
        assert _failed_components(caplog) == ["database"]


def _run_in_thread(target) -> threading.Thread:
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread


class TestReadinessVerdictThreads:
    """The two threads of a gunicorn worker share one check at a time."""

    def test_a_probe_during_a_check_waits_for_its_verdict(self, monkeypatch):
        verdict = middleware._ReadinessVerdict(ManualClock())
        started, release = threading.Event(), threading.Event()
        checks: list[str] = []

        def slow_database_check() -> bool:
            checks.append("database")
            started.set()
            return release.wait(5)

        monkeypatch.setattr(middleware, "_database_answers", slow_database_check)
        monkeypatch.setattr(middleware, "_cache_takes_writes", lambda: True)
        answers: dict[str, bool] = {}
        try:
            first = _run_in_thread(lambda: answers.update(first=verdict.current()))
            assert started.wait(5)
            second = _run_in_thread(lambda: answers.update(second=verdict.current()))
            second.join(0.2)
            assert second.is_alive(), "the second probe waits for the running check"
            assert checks == ["database"]
        finally:
            release.set()
        first.join(5)
        second.join(5)
        assert answers == {"first": True, "second": True}
        assert checks == ["database"]

    def test_a_probe_stops_waiting_for_a_hung_check(self, monkeypatch, caplog):
        monkeypatch.setattr(middleware, "READY_CHECK_WAIT_SECONDS", 0.1)
        verdict = middleware._ReadinessVerdict(ManualClock())
        started, release = threading.Event(), threading.Event()

        def hung_cache_check() -> bool:
            started.set()
            return release.wait(5)

        monkeypatch.setattr(middleware, "_database_answers", lambda: True)
        monkeypatch.setattr(middleware, "_cache_takes_writes", hung_cache_check)
        try:
            checking = _run_in_thread(verdict.current)
            assert started.wait(5)
            assert verdict.current() is False
            [warning] = [
                record.getMessage()
                for record in caplog.records
                if record.getMessage().startswith("health.ready.unavailable ")
            ]
            assert warning == (
                "health.ready.unavailable component=cache reason=check_still_running"
            )
        finally:
            release.set()
        checking.join(5)
        assert not checking.is_alive()
