"""The CSP report endpoint answers 204 to anything a poster sends.

It is unauthenticated and reachable on both URL confs, so the report shapes it
walks — the legacy ``{"csp-report": {...}}`` envelope and the Reporting API
array — have to be checked for real before their fields are read. A body like
``{"csp-report": "x"}`` is one hand-crafted POST away and must not be a 500.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from django.test import Client

from apps.shared.csp_report import (
    _MAX_LOGGED_FIELD_CHARS,
    _MAX_REPORT_BYTES,
    _MAX_REPORTS_PER_POST,
)

URL = "/api/csp-report/"

pytestmark = pytest.mark.django_db


def _post(payload, *, raw: str | None = None):
    body = raw if raw is not None else json.dumps(payload)
    return Client().post(URL, data=body, content_type="application/json")


@pytest.fixture
def report_logger():
    with patch("apps.shared.csp_report.logger") as mock_logger:
        yield mock_logger


def _rendered(mock_logger, index: int = 0) -> str:
    """The log line as it reaches the handler, format string applied."""
    fmt, *args = mock_logger.warning.call_args_list[index][0]
    return fmt % tuple(args)


class TestMalformedBodies:
    @pytest.mark.parametrize(
        "payload",
        [
            {"csp-report": "a string, not a report"},
            {"csp-report": ["a", "list"]},
            {"csp-report": 42},
            {"csp-report": None},
            ["not a dict", 5, None],
            [{"body": "a string"}, {"body": ["x"]}],
            "a bare string",
            42,
            None,
        ],
        ids=repr,
    )
    def test_junk_payload_returns_204_and_logs_no_violation(
        self, tenant, report_logger, payload
    ):
        resp = _post(payload)

        assert resp.status_code == 204
        # Nothing report-shaped survived the filter, so there is nothing to log.
        assert report_logger.warning.call_count == 0

    def test_unparseable_body_returns_204(self, tenant):
        resp = _post(None, raw="{not json at all")

        assert resp.status_code == 204


class TestWellFormedReports:
    def test_legacy_envelope_is_logged(self, tenant, report_logger):
        resp = _post(
            {
                "csp-report": {
                    "violated-directive": "img-src",
                    "blocked-uri": "https://evil.example/pixel.png",
                    "source-file": "https://tenant.example/app.js",
                }
            }
        )

        assert resp.status_code == 204
        assert report_logger.warning.call_count == 1
        assert "csp.violation host=" in report_logger.warning.call_args[0][0]

    def test_reporting_api_array_keeps_only_the_object_entries(
        self, tenant, report_logger
    ):
        resp = _post(
            [
                {"body": {"effectiveDirective": "script-src"}},
                {"body": "junk"},
                "junk",
                {"effectiveDirective": "style-src"},
            ]
        )

        assert resp.status_code == 204
        # The two object-shaped reports are logged; the junk entries are dropped.
        assert report_logger.warning.call_count == 2


class TestDocumentIsRecorded:
    """The logged line names the page the violation came from.

    ``source-file`` is the script, which for a bundled SPA is the same chunk on
    every route, so without the document a reviewer cannot tell which page to
    look at.
    """

    def test_legacy_document_uri_is_logged(self, tenant, report_logger):
        resp = _post(
            {
                "csp-report": {
                    "document-uri": "https://tenant.example/invoices",
                    "violated-directive": "frame-src",
                    "blocked-uri": "blob",
                }
            }
        )

        assert resp.status_code == 204
        line = _rendered(report_logger)
        assert "doc=" in line
        assert "https://tenant.example/invoices" in line

    def test_reporting_api_document_url_is_logged(self, tenant, report_logger):
        resp = _post(
            [
                {
                    "body": {
                        "documentURL": "https://tenant.example/abos",
                        "effectiveDirective": "worker-src",
                    }
                }
            ]
        )

        assert resp.status_code == 204
        line = _rendered(report_logger)
        assert "doc=" in line
        assert "https://tenant.example/abos" in line

    def test_a_report_carrying_no_document_still_logs(self, tenant, report_logger):
        resp = _post({"csp-report": {"violated-directive": "img-src"}})

        assert resp.status_code == 204
        assert report_logger.warning.call_count == 1
        assert "doc=None" in _rendered(report_logger)


class TestFloodProtection:
    """One anonymous POST must not be able to write an unbounded number of log
    lines: the container ships every logger to a single capped stream, so a
    flood here evicts the auth / lockout / authz records."""

    def test_a_long_report_array_is_capped(self, tenant, report_logger):
        resp = _post([{"effectiveDirective": "script-src"}] * 500)

        assert resp.status_code == 204
        # The capped reports plus ONE aggregated line saying what was dropped.
        assert report_logger.warning.call_count == _MAX_REPORTS_PER_POST + 1
        first_line = report_logger.warning.call_args_list[0][0][0]
        assert "csp.violation.truncated" in first_line

    def test_a_short_array_is_logged_in_full(self, tenant, report_logger):
        resp = _post([{"effectiveDirective": "script-src"}] * 3)

        assert resp.status_code == 204
        assert report_logger.warning.call_count == 3

    def test_one_report_cannot_write_an_oversized_line(self, tenant, report_logger):
        """The per-POST cap bounds how MANY lines a body writes, not how wide
        each one is. Every field of a report is attacker-controlled, so a body
        that fits under the size cap must still not turn into a log line of
        comparable size."""
        long_document = "A" * 20_000
        payload = {
            "csp-report": {
                "document-uri": long_document,
                "violated-directive": "D" * 5_000,
                "blocked-uri": "B" * 15_000,
                "source-file": "C" * 10_000,
            }
        }
        assert len(json.dumps(payload)) < _MAX_REPORT_BYTES

        resp = _post(payload)

        assert resp.status_code == 204
        line = _rendered(report_logger)
        # Four fields at the per-field bound, plus the host / ip / literals.
        assert len(line) < 2_500
        assert long_document not in line
        # Truncated, not dropped: enough of the document survives to identify it.
        assert "A" * _MAX_LOGGED_FIELD_CHARS in line

    def test_a_body_over_the_size_cap_is_dropped_unread(self, tenant, report_logger):
        oversized = json.dumps([{"effectiveDirective": "script-src"}] * 5000)
        assert len(oversized) > _MAX_REPORT_BYTES

        resp = _post(None, raw=oversized)

        assert resp.status_code == 204
        # Refused on the declared length — never parsed, never logged.
        assert report_logger.warning.call_count == 0
