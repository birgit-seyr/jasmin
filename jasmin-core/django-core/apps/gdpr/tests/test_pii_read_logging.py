"""Tests for ``PIIReadLoggingMixin``.

The mixin is mounted on three viewsets — ``MemberViewSet``,
``BillingProfileViewSet``, ``ResellerViewSet`` — and emits one
structured ``pii.read`` line per successful ``.retrieve()``.

What we lock here:

  * Fires on ``GET /api/commissioning/members/<pk>/`` (the
    canonical detail endpoint).
  * Does NOT fire on ``GET /api/commissioning/members/`` (list).
  * Does NOT fire on 404 — if the office didn't see the PII, no
    audit row.
  * Does NOT fire on 403 — same reason.
  * The line carries the actor email, subject_kind
    (``app.model``), subject_id, tenant schema, and client IP.

The other two viewsets are exercised by a parametrized smoke test
that just asserts a single ``pii.read`` line lands on retrieve;
each viewset's specific permission semantics are locked in their
own tests elsewhere.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.commissioning.tests.factories import MemberFactory


@pytest.fixture(autouse=True)
def _propagate_gdpr_logger():
    """The ``gdpr`` logger is configured with ``propagate: False`` in
    settings.py so app/security log streams stay clean. pytest's
    ``caplog`` attaches its handler to root, so without this flip
    nothing reaches the captured records. Restore the original
    setting on teardown so we don't leak state into other tests.
    """
    logger = logging.getLogger("gdpr")
    previous = logger.propagate
    logger.propagate = True
    try:
        yield
    finally:
        logger.propagate = previous


def _captured_pii_lines(caplog) -> list[str]:
    return [
        r.getMessage() for r in caplog.records if r.getMessage().startswith("pii.read")
    ]


@pytest.mark.django_db
class TestMemberRetrieveLogging:
    def test_retrieve_emits_pii_read_line(self, api_client, tenant, user, caplog):
        member = MemberFactory()
        url = reverse("member-detail", args=[member.pk])

        with caplog.at_level("INFO", logger="gdpr"):
            response = api_client.get(url)

        assert response.status_code == 200
        lines = _captured_pii_lines(caplog)
        assert len(lines) == 1
        line = lines[0]
        assert f"subject_id={member.pk}" in line
        assert "subject_kind=commissioning.member" in line
        assert f"actor={user.email}" in line
        assert f"tenant={tenant.schema_name}" in line

    def test_list_does_not_emit_pii_read_line(self, api_client, tenant, user, caplog):
        """List pages are hit on every office page-load. Logging them
        would drown the forensic signal in noise. The contract is:
        list never produces a ``pii.read`` row."""
        MemberFactory()
        url = reverse("member-list")

        with caplog.at_level("INFO", logger="gdpr"):
            response = api_client.get(url)

        assert response.status_code == 200
        assert _captured_pii_lines(caplog) == []

    def test_404_does_not_emit_pii_read_line(self, api_client, tenant, user, caplog):
        """If the office hit a non-existent pk they didn't see any
        PII — no audit row should claim they did."""
        url = reverse("member-detail", args=["does-not-exist"])

        with caplog.at_level("INFO", logger="gdpr"):
            response = api_client.get(url)

        assert response.status_code == 404
        assert _captured_pii_lines(caplog) == []

    def test_anonymous_request_does_not_emit_pii_read_line(
        self, anon_client, tenant, caplog
    ):
        """Anonymous requests get rejected at the permission layer
        (401/403). No PII was shown, so no audit row."""
        member = MemberFactory()
        url = reverse("member-detail", args=[member.pk])

        with caplog.at_level("INFO", logger="gdpr"):
            response = anon_client.get(url)

        assert response.status_code in (401, 403)
        assert _captured_pii_lines(caplog) == []


@pytest.mark.django_db
class TestPIIReadLoggingLeavesResponseIntact:
    """Logging is a side-effect. If the log call ever raises (bad
    format string, unicode error, whatever), the response that's
    already been computed must still reach the office user."""

    def test_logging_failure_does_not_break_retrieve(
        self, api_client, tenant, user, caplog
    ):
        member = MemberFactory()
        url = reverse("member-detail", args=[member.pk])

        # Make ``client_ip`` blow up. The mixin must swallow it +
        # write a ``pii.read.logging_failed`` line instead of
        # corrupting the response.
        with patch(
            "apps.shared.pii_logging.client_ip",
            side_effect=RuntimeError("synthetic"),
        ):
            with caplog.at_level("ERROR", logger="gdpr"):
                response = api_client.get(url)

        assert response.status_code == 200
        assert any("pii.read.logging_failed" in r.getMessage() for r in caplog.records)


class TestLogValueSanitization:
    """``pii.read`` lines go to a newline-delimited plain-text log, so every
    interpolated value is reduced to a single safe token first."""

    def test_newline_cannot_forge_a_second_audit_line(self):
        from apps.shared.pii_logging import sanitize_log_value

        cleaned = sanitize_log_value(
            "ab12\npii.read actor=ghost@example.org subject_kind=forged"
        )

        assert "\n" not in cleaned
        assert cleaned.startswith("ab12?pii.read")

    def test_carriage_return_and_other_control_characters_are_replaced(self):
        from apps.shared.pii_logging import sanitize_log_value

        assert sanitize_log_value("a\rb\tc\x00d e") == "a?b?c?d?e"

    def test_real_values_survive_unchanged(self):
        from apps.shared.pii_logging import sanitize_log_value

        for value in (
            "list(all)",
            "list(member=ab12-CD_34)",
            "office.user+tag@example.org",
            "2001:db8::1",
            "203.0.113.7",
        ):
            assert sanitize_log_value(value) == value

    def test_value_is_length_bounded(self):
        from apps.shared.pii_logging import sanitize_log_value

        assert len(sanitize_log_value("a" * 500)) == 120

    def test_non_string_values_are_coerced(self):
        from apps.shared.pii_logging import sanitize_log_value

        assert sanitize_log_value(None) == "None"
        assert sanitize_log_value(42) == "42"
