"""Tenant email sending is DISABLED when the tenant has no SMTP host.

Design decision: a tenant that has not configured its own SMTP must NOT
fall back to the platform ``EMAIL_*`` account — that transport is reserved
for operator / ops alerts (``mail_admins``). Tenant mail goes out through
the tenant's own SMTP or not at all. ``EmailService.send_email`` returns
False and never opens a connection.

Two layers enforce this and are pinned here:
  * ``send_email`` early-returns False (before rendering) when the active
    config has no SMTP host.
  * ``_get_connection`` is the authoritative backstop — it raises rather
    than let Django's ``get_connection(host=None, …)`` fall back to
    ``settings.EMAIL_HOST``.
"""

from __future__ import annotations

from unittest import mock

import pytest

from apps.shared.tenants.email_service import EmailService
from apps.shared.tenants.models import TenantEmailConfig


def _config(tenant, **overrides) -> TenantEmailConfig:
    defaults = dict(
        tenant=tenant,
        from_email="noreply@example.org",
        from_name="Test Tenant",
        is_active=True,
    )
    defaults.update(overrides)
    return TenantEmailConfig.objects.create(**defaults)


@pytest.mark.django_db
class TestSendingDisabledWithoutSmtp:
    def test_has_smtp_configured_property(self, tenant):
        cfg = _config(tenant)  # no smtp_host
        assert cfg.has_smtp_configured is False
        cfg.smtp_host = "smtp.example.org"
        assert cfg.has_smtp_configured is True
        cfg.smtp_host = "   "  # whitespace-only counts as unset
        assert cfg.has_smtp_configured is False

    def test_send_email_disabled_without_smtp_host(self, tenant):
        """Active config, but no SMTP host → send is a no-op returning
        False, and the transport is never even opened (no fallback)."""
        _config(tenant)  # active, but smtp_host unset
        service = EmailService(tenant.schema_name)

        with mock.patch.object(
            EmailService, "_get_connection", autospec=True
        ) as get_conn:
            sent = service.send_email(
                to_emails=["someone@example.org"],
                context={},
                slug="tenants.smtp_test",
            )

        assert sent is False
        assert get_conn.call_count == 0

    def test_get_connection_refuses_without_host(self, tenant):
        """The authoritative backstop: even called directly, it refuses to
        build a connection (which would fall back to the platform host)."""
        _config(tenant)  # no smtp_host
        service = EmailService(tenant.schema_name)

        with pytest.raises(ValueError, match="No SMTP host configured"):
            service._get_connection()

    def test_send_email_proceeds_when_smtp_host_set(self, tenant):
        """Positive control: a configured host does NOT get blocked — the
        send reaches the assemble/send step. Rendering + transport are
        stubbed so the test stays template- and network-independent."""
        _config(tenant, smtp_host="smtp.example.org", smtp_port=587)
        service = EmailService(tenant.schema_name)

        with (
            mock.patch.object(
                EmailService,
                "_render_body",
                autospec=True,
                return_value=("Subject", "<p>hi</p>", "hi", "tpl"),
            ),
            mock.patch.object(
                EmailService, "_build_and_send", autospec=True, return_value=True
            ) as build_and_send,
        ):
            sent = service.send_email(
                to_emails=["someone@example.org"],
                context={},
                slug="tenants.smtp_test",
            )

        assert sent is True
        assert build_and_send.call_count == 1
